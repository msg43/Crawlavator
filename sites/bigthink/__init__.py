"""
Big Think Interviews Plugin
Scrapes transcripts from Big Think Interview series
"""

import os
import re
import json
import requests
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

from .. import BaseSite, ContentItem, register_site


@register_site
class BigThinkSite(BaseSite):
    """Big Think Interviews site plugin"""
    
    SITE_ID = "bigthink"
    SITE_NAME = "Big Think Interviews"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript"]
    CATEGORIES = ["interview"]
    
    BASE_URL = "https://bigthink.com"
    SERIES_URL = "https://bigthink.com/series/the-big-think-interview/"
    
    def __init__(self):
        self.indexed_content: Dict[str, ContentItem] = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def get_config_fields(self) -> List[Dict[str, Any]]:
        return []
    
    def check_auth(self) -> Tuple[bool, str]:
        return True, "No authentication required"
    
    def login(self, **credentials) -> Tuple[bool, str]:
        return True, "No authentication required"
    
    def index_content(self, progress_callback=None) -> List[ContentItem]:
        """Index all interviews from the series page"""
        items = []
        
        if progress_callback:
            progress_callback("Fetching Big Think Interview series...")
        
        try:
            # Fetch the series landing page
            response = self.session.get(self.SERIES_URL, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Find all interview links on the series page
            # Big Think uses article cards or links to individual interviews
            interview_links = []
            
            # Strategy 1: Look for article links in the main content
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Interview URLs typically follow pattern: /series/the-big-think-interview/[topic]/
                if '/series/the-big-think-interview/' in href and href != self.SERIES_URL:
                    full_url = urljoin(self.BASE_URL, href)
                    if full_url not in interview_links:
                        interview_links.append(full_url)
            
            if progress_callback:
                progress_callback(f"Found {len(interview_links)} interviews")
            
            # Index each interview
            for idx, interview_url in enumerate(interview_links, 1):
                if progress_callback and idx % 5 == 0:
                    progress_callback(f"Indexing interview {idx}/{len(interview_links)}...")
                
                try:
                    item = self._index_interview(interview_url)
                    if item and item.id not in self.indexed_content:
                        self.indexed_content[item.id] = item
                        items.append(item)
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"Error indexing {interview_url}: {str(e)[:50]}")
                    continue
            
            if progress_callback:
                progress_callback(f"Successfully indexed {len(items)} interviews")
            
            return items
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return items
    
    def _index_interview(self, url: str) -> Optional[ContentItem]:
        """Index a single interview page"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Extract title
            title = None
            title_elem = soup.find('h1')
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            if not title:
                title = soup.find('title')
                if title:
                    title = title.get_text(strip=True).replace(' | Big Think', '')
            
            # Extract guest/interviewee name
            guest = None
            guest_elem = soup.find(['span', 'div'], class_=re.compile(r'author|guest|interviewee', re.I))
            if guest_elem:
                guest = guest_elem.get_text(strip=True)
            
            # Try to find guest in "with" text
            if not guest:
                with_match = re.search(r'with\s+([^—\n]+)', title or '', re.I)
                if with_match:
                    guest = with_match.group(1).strip()
            
            # Extract date
            date_str = None
            date_elem = soup.find(['time', 'span'], class_=re.compile(r'date|time', re.I))
            if date_elem:
                date_text = date_elem.get('datetime') or date_elem.get_text(strip=True)
                try:
                    dt = datetime.fromisoformat(date_text.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d')
                except:
                    pass
            
            # Extract description
            description = None
            desc_elem = soup.find(['meta'], attrs={'name': 'description'})
            if desc_elem:
                description = desc_elem.get('content', '')
            
            # Create unique ID from URL
            url_parts = url.rstrip('/').split('/')
            slug = url_parts[-1] if url_parts else 'unknown'
            item_id = f"bigthink_{self._sanitize_id(slug)}"
            
            # Build full title with guest if available
            full_title = title or slug.replace('-', ' ').title()
            if guest and guest not in full_title:
                full_title = f"{full_title} - {guest}"
            
            return ContentItem(
                id=item_id,
                title=full_title,
                url=url,
                asset_type="transcript",
                category="interview",
                subcategory="The Big Think Interview",
                date=date_str,
                description=description
            )
            
        except Exception as e:
            return None
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download interview transcript"""
        
        try:
            if progress_callback:
                progress_callback(f"Fetching transcript: {item.title}")
            
            # Fetch the interview page
            response = self.session.get(item.url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Extract transcript content
            transcript_text = self._extract_transcript(soup)
            
            if not transcript_text or len(transcript_text) < 100:
                return False, "No transcript content found"
            
            # Save transcript
            os.makedirs(output_dir, exist_ok=True)
            
            safe_title = self._safe_filename(item.title)
            txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
            
            # Create header
            header = f"# {item.title}\n"
            if item.date:
                header += f"Date: {item.date}\n"
            header += f"Source: Big Think Interviews\n"
            header += f"URL: {item.url}\n\n"
            header += "---\n\n"
            
            # Write transcript
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(header + transcript_text)
            
            # Save metadata
            metadata = {
                'id': item.id,
                'title': item.title,
                'url': item.url,
                'date': item.date,
                'source': 'Big Think Interviews',
                'asset_type': 'transcript'
            }
            
            metadata_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            if progress_callback:
                progress_callback(f"✓ Saved: {safe_title}")
            
            return True, txt_path
            
        except Exception as e:
            error_msg = f"Error downloading {item.title}: {str(e)}"
            if progress_callback:
                progress_callback(error_msg)
            return False, error_msg
    
    def _extract_transcript(self, soup: BeautifulSoup) -> str:
        """Extract transcript text from Big Think page"""
        transcript_parts = []
        
        # Strategy 1: Look for main article/content area
        main_content = soup.find(['article', 'main'])
        if main_content:
            # Remove navigation, headers, footers
            for unwanted in main_content.find_all(['nav', 'header', 'footer', 'aside', 'script', 'style']):
                unwanted.decompose()
            
            # Get all paragraphs
            paragraphs = main_content.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Filter out very short lines (likely UI elements)
                if len(text) > 20:
                    transcript_parts.append(text)
        
        # Strategy 2: Look for specific transcript container
        if not transcript_parts:
            transcript_container = soup.find(['div', 'section'], class_=re.compile(r'transcript|content', re.I))
            if transcript_container:
                text = transcript_container.get_text(separator='\n\n', strip=True)
                if len(text) > 100:
                    return text
        
        # Join all parts
        if transcript_parts:
            return '\n\n'.join(transcript_parts)
        
        return ""
    
    def _sanitize_id(self, text: str) -> str:
        """Create a safe ID from text"""
        safe = re.sub(r'[^\w\s-]', '', text.lower())
        safe = re.sub(r'[-\s]+', '_', safe)
        return safe[:50]
    
    def _safe_filename(self, name: str) -> str:
        """Convert string to safe filename"""
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        return safe[:100] if safe else 'unknown'
    
    def close(self):
        """Clean up resources"""
        self.session.close()

