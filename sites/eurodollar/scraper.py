"""
EDU Content Scraper
Discovers and indexes all content from eurodollar.university
"""

import re
import time
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import Page

from .auth import EDUAuth


@dataclass
class ContentItem:
    """Represents a single content item"""
    id: str
    title: str
    url: str
    asset_type: str  # video, pdf, audio, article, transcript
    category: str    # membership, dda, daily-briefing
    subcategory: str = ""  # the-basics, classroom, qna, etc.
    date: str = ""
    description: str = ""
    download_url: Optional[str] = None
    thumbnail: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


class EDUScraper:
    """Scrapes and indexes content from eurodollar.university"""
    
    BASE_URL = "https://www.eurodollar.university"
    
    # Content section URLs
    SECTIONS = {
        # Membership content
        "the-basics": "/videos/the-basics",
        "classroom": "/videos/member-podcasts",
        "qna": "/videos/qas",
        "weekly-recap": "/videos/weekly-recap",
        "presentations": "/videos/presentations",
        "conversations": "/videos/conversations",
        "guest-presentations": "/videos/guest-presentations",
        "digitized": "/videos/digitized",
        "youtube-adfree": "/youtube-show-adfree",
        "audio": "/audioother",
        "transcripts": "/transcripts",
        "resources": "/resources",
        
        # DDA content
        "dda": "/dda",
        "substack": "/substack",
        "portfolios": "/portfolios",
        
        # Daily Briefing
        "daily-briefing": "/daily-briefing",
        "daily-briefing-archive": "/daily-briefing-2023-24",
    }
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
        self.indexed_content: Dict[str, ContentItem] = {}
        self.errors: List[Dict] = []
        self.restricted: List[Dict] = []
    
    def _get_page_soup(self, page: Page, url: str, 
                       on_error: Optional[Callable] = None) -> Optional[BeautifulSoup]:
        """Navigate to URL and return BeautifulSoup, handling errors gracefully"""
        try:
            full_url = urljoin(self.BASE_URL, url)
            response = page.goto(full_url, wait_until='networkidle', timeout=30000)
            
            if response and response.status == 403:
                self.restricted.append({
                    "url": full_url,
                    "reason": "Access denied (403)"
                })
                if on_error:
                    on_error(f"Access denied: {url}")
                return None
            
            if response and response.status == 404:
                self.errors.append({
                    "url": full_url,
                    "error": "Page not found (404)"
                })
                if on_error:
                    on_error(f"Not found: {url}")
                return None
            
            # Check if redirected to login
            if '/account/login' in page.url.lower():
                self.restricted.append({
                    "url": full_url,
                    "reason": "Requires authentication"
                })
                if on_error:
                    on_error(f"Auth required: {url}")
                return None
            
            page.wait_for_timeout(1000)
            html = page.content()
            return BeautifulSoup(html, 'lxml')
            
        except Exception as e:
            self.errors.append({
                "url": url,
                "error": str(e)
            })
            if on_error:
                on_error(f"Error loading {url}: {str(e)}")
            return None
    
    def _generate_id(self, category: str, subcategory: str, title: str) -> str:
        """Generate a unique ID for a content item"""
        # Clean title for ID
        clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', title.lower())
        clean_title = re.sub(r'\s+', '-', clean_title)[:50]
        return f"{category}/{subcategory}/{clean_title}"
    
    def index_video_section(self, page: Page, section_key: str,
                            progress_callback: Optional[Callable] = None) -> List[ContentItem]:
        """Index all videos in a video section"""
        items = []
        section_url = self.SECTIONS.get(section_key, "")
        
        if progress_callback:
            progress_callback(f"Indexing {section_key}...")
        
        soup = self._get_page_soup(page, section_url, progress_callback)
        if not soup:
            return items
        
        # Find video items - Squarespace video gallery structure
        video_links = soup.select('a[href*="/videos/v/"]')
        
        for link in video_links:
            try:
                href = link.get('href', '')
                if not href:
                    continue
                
                # Get title
                title_elem = link.select_one('h4, h3, h2, .video-title')
                if title_elem:
                    title = title_elem.get_text(strip=True)
                else:
                    title = link.get_text(strip=True) or "Untitled"
                
                # Get thumbnail
                img = link.select_one('img')
                thumbnail = img.get('src') if img else None
                
                # Get date
                date_elem = link.find_parent().select_one('time, .date, [class*="date"]')
                date = ""
                if date_elem:
                    date = date_elem.get_text(strip=True)
                else:
                    # Try to extract date from nearby text
                    parent_text = link.find_parent().get_text() if link.find_parent() else ""
                    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', parent_text)
                    if date_match:
                        date = date_match.group(1)
                
                # Get description
                desc_elem = link.find_parent().select_one('p, .description')
                description = desc_elem.get_text(strip=True) if desc_elem else ""
                
                item = ContentItem(
                    id=self._generate_id("membership", section_key, title),
                    title=title,
                    url=urljoin(self.BASE_URL, href),
                    asset_type="video",
                    category="membership",
                    subcategory=section_key,
                    date=date,
                    description=description[:200],
                    thumbnail=thumbnail
                )
                
                if item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)
                    
            except Exception as e:
                self.errors.append({
                    "url": section_url,
                    "error": f"Error parsing video: {str(e)}"
                })
        
        if progress_callback:
            progress_callback(f"Found {len(items)} videos in {section_key}")
        
        return items
    
    def index_audio_section(self, page: Page,
                            progress_callback: Optional[Callable] = None) -> List[ContentItem]:
        """Index audio files and slides from /audioother"""
        items = []
        
        if progress_callback:
            progress_callback("Indexing audio files...")
        
        soup = self._get_page_soup(page, self.SECTIONS["audio"], progress_callback)
        if not soup:
            return items
        
        # Find download links
        download_links = soup.select('a[href*=".m4a"], a[href*=".mp3"], a[href*=".pdf"][href*="download"]')
        
        for link in download_links:
            try:
                href = link.get('href', '')
                if not href:
                    continue
                
                # Determine asset type
                if '.m4a' in href.lower() or '.mp3' in href.lower():
                    asset_type = "audio"
                elif '.pdf' in href.lower():
                    asset_type = "slides"
                else:
                    continue
                
                # Get title from nearby heading or link text
                parent = link.find_parent(['div', 'li', 'section'])
                title_elem = parent.select_one('h2, h3, h4, strong') if parent else None
                title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)
                
                if not title or title.lower() == 'download':
                    # Extract from filename
                    filename = href.split('/')[-1].split('?')[0]
                    title = re.sub(r'\.(m4a|mp3|pdf)$', '', filename, flags=re.IGNORECASE)
                    title = title.replace('+', ' ').replace('%20', ' ')
                
                item = ContentItem(
                    id=self._generate_id("membership", "audio", title),
                    title=title,
                    url=urljoin(self.BASE_URL, self.SECTIONS["audio"]),
                    asset_type=asset_type,
                    category="membership",
                    subcategory="audio",
                    download_url=href if href.startswith('http') else urljoin(self.BASE_URL, href)
                )
                
                if item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)
                    
            except Exception as e:
                self.errors.append({
                    "url": self.SECTIONS["audio"],
                    "error": f"Error parsing audio: {str(e)}"
                })
        
        if progress_callback:
            progress_callback(f"Found {len(items)} audio/slide files")
        
        return items
    
    def index_dda_articles(self, page: Page, max_pages: int = 50,
                           progress_callback: Optional[Callable] = None) -> List[ContentItem]:
        """Index Deep Dive Analysis articles"""
        items = []
        
        if progress_callback:
            progress_callback("Indexing DDA articles...")
        
        soup = self._get_page_soup(page, self.SECTIONS["dda"], progress_callback)
        if not soup:
            return items
        
        # Find blog post links
        article_links = soup.select('article a[href*="/dda/"], a.blog-title, a[href*="/blog/"]')
        
        # Also try generic article structure
        if not article_links:
            article_links = soup.select('a[href*="/dda"]')
        
        for link in article_links:
            try:
                href = link.get('href', '')
                if not href or href == '/dda' or href == '/dda/':
                    continue
                
                title = link.get_text(strip=True)
                if not title:
                    title_elem = link.select_one('h1, h2, h3, h4')
                    title = title_elem.get_text(strip=True) if title_elem else "Untitled DDA"
                
                # Get date
                parent = link.find_parent(['article', 'div', 'li'])
                date_elem = parent.select_one('time, .blog-date, [class*="date"]') if parent else None
                date = date_elem.get_text(strip=True) if date_elem else ""
                
                item = ContentItem(
                    id=self._generate_id("dda", "articles", title),
                    title=title,
                    url=urljoin(self.BASE_URL, href),
                    asset_type="article",
                    category="dda",
                    subcategory="articles",
                    date=date
                )
                
                if item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)
                    
            except Exception as e:
                self.errors.append({
                    "url": self.SECTIONS["dda"],
                    "error": f"Error parsing DDA article: {str(e)}"
                })
        
        if progress_callback:
            progress_callback(f"Found {len(items)} DDA articles")
        
        return items
    
    def index_daily_briefings(self, page: Page,
                               progress_callback: Optional[Callable] = None) -> List[ContentItem]:
        """Index Daily Briefing PDFs"""
        items = []
        
        for section_key in ["daily-briefing", "daily-briefing-archive"]:
            if progress_callback:
                progress_callback(f"Indexing {section_key}...")
            
            soup = self._get_page_soup(page, self.SECTIONS[section_key], progress_callback)
            if not soup:
                continue
            
            # Find accordion items or PDF links
            accordions = soup.select('[class*="accordion"], button[class*="accordion"]')
            
            for accordion in accordions:
                try:
                    title = accordion.get_text(strip=True)
                    if not title:
                        continue
                    
                    # The PDF content is typically in the accordion panel
                    # We'll need to expand these when downloading
                    item = ContentItem(
                        id=self._generate_id("daily-briefing", section_key, title),
                        title=title,
                        url=urljoin(self.BASE_URL, self.SECTIONS[section_key]),
                        asset_type="pdf",
                        category="daily-briefing",
                        subcategory=section_key
                    )
                    
                    if item.id not in self.indexed_content:
                        self.indexed_content[item.id] = item
                        items.append(item)
                        
                except Exception as e:
                    self.errors.append({
                        "url": self.SECTIONS[section_key],
                        "error": f"Error parsing briefing: {str(e)}"
                    })
            
            # Also look for direct PDF links
            pdf_links = soup.select('a[href*=".pdf"]')
            for link in pdf_links:
                try:
                    href = link.get('href', '')
                    title = link.get_text(strip=True) or "Daily Briefing"
                    
                    item = ContentItem(
                        id=self._generate_id("daily-briefing", section_key, title),
                        title=title,
                        url=urljoin(self.BASE_URL, self.SECTIONS[section_key]),
                        asset_type="pdf",
                        category="daily-briefing",
                        subcategory=section_key,
                        download_url=href if href.startswith('http') else urljoin(self.BASE_URL, href)
                    )
                    
                    if item.id not in self.indexed_content:
                        self.indexed_content[item.id] = item
                        items.append(item)
                        
                except Exception:
                    pass
        
        if progress_callback:
            progress_callback(f"Found {len(items)} daily briefings")
        
        return items
    
    def index_transcripts(self, page: Page,
                          progress_callback: Optional[Callable] = None) -> List[ContentItem]:
        """Index transcript pages"""
        items = []
        
        if progress_callback:
            progress_callback("Indexing transcripts...")
        
        soup = self._get_page_soup(page, self.SECTIONS["transcripts"], progress_callback)
        if not soup:
            return items
        
        # Find accordion/expandable sections containing transcripts
        accordions = soup.select('button[class*="accordion"], [role="button"]')
        
        for accordion in accordions:
            try:
                title = accordion.get_text(strip=True)
                if not title or 'expand' in title.lower():
                    continue
                
                item = ContentItem(
                    id=self._generate_id("membership", "transcripts", title),
                    title=title,
                    url=urljoin(self.BASE_URL, self.SECTIONS["transcripts"]),
                    asset_type="transcript",
                    category="membership",
                    subcategory="transcripts"
                )
                
                if item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)
                    
            except Exception as e:
                self.errors.append({
                    "url": self.SECTIONS["transcripts"],
                    "error": f"Error parsing transcript: {str(e)}"
                })
        
        if progress_callback:
            progress_callback(f"Found {len(items)} transcripts")
        
        return items
    
    def index_all(self, progress_callback: Optional[Callable] = None) -> Dict[str, List[ContentItem]]:
        """Index all content from all sections"""
        page = self.auth.get_page()
        
        results = {
            "videos": [],
            "audio": [],
            "dda": [],
            "daily_briefing": [],
            "transcripts": []
        }
        
        try:
            # Index video sections (skip qna and weekly-recap per user request)
            video_sections = [
                "the-basics", "classroom",
                "presentations", "conversations", "guest-presentations",
                "digitized", "youtube-adfree"
            ]
            
            for section in video_sections:
                try:
                    items = self.index_video_section(page, section, progress_callback)
                    results["videos"].extend(items)
                    time.sleep(0.5)  # Be nice to the server
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"Error indexing {section}: {str(e)}")
                    self.errors.append({"section": section, "error": str(e)})
            
            # Index audio
            try:
                results["audio"] = self.index_audio_section(page, progress_callback)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error indexing audio: {str(e)}")
            
            # Index DDA
            try:
                results["dda"] = self.index_dda_articles(page, progress_callback=progress_callback)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error indexing DDA: {str(e)}")
            
            # Index Daily Briefings - DISABLED per user request
            # try:
            #     results["daily_briefing"] = self.index_daily_briefings(page, progress_callback)
            # except Exception as e:
            #     if progress_callback:
            #         progress_callback(f"Error indexing daily briefings: {str(e)}")
            
            # Index Transcripts
            try:
                results["transcripts"] = self.index_transcripts(page, progress_callback)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error indexing transcripts: {str(e)}")
            
        finally:
            page.close()
        
        # Summary
        total = sum(len(v) for v in results.values())
        if progress_callback:
            progress_callback(f"Indexing complete: {total} items, {len(self.restricted)} restricted, {len(self.errors)} errors")
        
        return results
    
    def get_all_items(self) -> List[ContentItem]:
        """Get all indexed content items"""
        return list(self.indexed_content.values())
    
    def get_items_by_category(self, category: str) -> List[ContentItem]:
        """Get items filtered by category"""
        return [item for item in self.indexed_content.values() if item.category == category]
    
    def get_items_by_type(self, asset_type: str) -> List[ContentItem]:
        """Get items filtered by asset type"""
        return [item for item in self.indexed_content.values() if item.asset_type == asset_type]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get indexing summary"""
        items = list(self.indexed_content.values())
        
        by_category = {}
        by_type = {}
        
        for item in items:
            by_category[item.category] = by_category.get(item.category, 0) + 1
            by_type[item.asset_type] = by_type.get(item.asset_type, 0) + 1
        
        return {
            "total_items": len(items),
            "by_category": by_category,
            "by_type": by_type,
            "restricted_count": len(self.restricted),
            "error_count": len(self.errors),
            "restricted": self.restricted,
            "errors": self.errors
        }

