"""
Fareed Zakaria GPS Plugin
CNN podcast with transcripts available on cnn.com
"""

import os
import re
import json
import requests
import feedparser
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

from .. import BaseSite, ContentItem, register_site


@register_site
class FareedZakariaSite(BaseSite):
    """Fareed Zakaria GPS podcast site plugin"""
    
    SITE_ID = "fareed_zakaria"
    SITE_NAME = "Fareed Zakaria GPS"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript", "audio"]
    CATEGORIES = ["podcast"]
    
    BASE_URL = "https://www.cnn.com"
    RSS_URL = "http://rss.cnn.com/rss/cnn_gps.rss"
    
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
        """Index all episodes from RSS feed"""
        items = []
        
        if progress_callback:
            progress_callback("Fetching Fareed Zakaria GPS RSS feed...")
        
        try:
            feed = feedparser.parse(self.RSS_URL)
            
            if progress_callback:
                progress_callback(f"Found {len(feed.entries)} episodes")
            
            for entry in feed.entries:
                try:
                    title = entry.get('title', 'Unknown')
                    url = entry.get('link', '')
                    
                    # Get publication date
                    date_str = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        dt = datetime(*entry.published_parsed[:6])
                        date_str = dt.strftime('%Y-%m-%d')
                    
                    # Get description
                    description = entry.get('description', '') or entry.get('summary', '')
                    
                    # Get audio URL if available
                    audio_url = None
                    if hasattr(entry, 'enclosures') and entry.enclosures:
                        for enclosure in entry.enclosures:
                            if 'audio' in enclosure.get('type', ''):
                                audio_url = enclosure.get('href', '')
                                break
                    
                    # Create unique ID
                    item_id = f"fareed_zakaria_{self._sanitize_id(title)}"
                    
                    item = ContentItem(
                        id=item_id,
                        title=title,
                        url=url,
                        asset_type="transcript",
                        category="podcast",
                        subcategory="transcripts",
                        date=date_str,
                        description=description,
                        download_url=audio_url
                    )
                    
                    if item.id not in self.indexed_content:
                        self.indexed_content[item.id] = item
                        items.append(item)
                        
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"Error parsing entry: {e}")
                    continue
            
            if progress_callback:
                progress_callback(f"Indexed {len(items)} episodes")
            
            return items
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return items
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download episode transcript from CNN"""
        
        try:
            if progress_callback:
                progress_callback(f"Fetching transcript: {item.title}")
            
            # Fetch the episode page
            response = self.session.get(item.url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Extract metadata
            metadata = self._extract_metadata(soup, item)
            
            # Find transcript content on CNN page
            # CNN uses various classes for transcript content
            transcript_content = None
            
            # Strategy 1: Look for transcript-specific divs
            transcript_div = soup.find(['div', 'section'], class_=re.compile(r'transcript|zn-body__paragraph', re.I))
            if transcript_div:
                transcript_content = transcript_div
            
            # Strategy 2: Look for article body
            if not transcript_content:
                transcript_content = soup.find(['article', 'div'], class_=re.compile(r'article-body|pg-rail-tall__body'))
            
            # Strategy 3: Look for main content area
            if not transcript_content:
                transcript_content = soup.find('div', class_=re.compile(r'body-text|pg-body'))
            
            # Strategy 4: Find all paragraphs in content area
            if not transcript_content:
                main_content = soup.find('main') or soup.find('article')
                if main_content:
                    transcript_content = main_content
            
            if not transcript_content or len(transcript_content.get_text(strip=True)) < 200:
                # Fall back to audio download if available
                if item.download_url:
                    return self._download_audio(item, output_dir, progress_callback)
                return False, "No transcript or audio found"
            
            # Extract text with proper formatting
            transcript_text = self._extract_formatted_text(transcript_content)
            
            # Save transcript
            os.makedirs(output_dir, exist_ok=True)
            
            safe_title = self._safe_filename(item.title)
            txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
            
            # Create header
            header = f"# {item.title}\n"
            if metadata.get('guest'):
                header += f"Guest: {metadata['guest']}\n"
            if item.date:
                header += f"Date: {item.date}\n"
            header += f"Source: Fareed Zakaria GPS (CNN)\n"
            header += f"URL: {item.url}\n\n"
            header += "---\n\n"
            
            # Write transcript
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(header + transcript_text)
            
            # Save metadata
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
    
    def _extract_metadata(self, soup: BeautifulSoup, item: ContentItem) -> Dict[str, Any]:
        """Extract metadata from episode page"""
        metadata = {
            'id': item.id,
            'title': item.title,
            'url': item.url,
            'date': item.date,
            'source': 'Fareed Zakaria GPS',
            'network': 'CNN',
            'asset_type': 'transcript'
        }
        
        # Try to extract guest name from title
        # Typical format: "GPS: Guest Name discusses topic" or "Interview with Guest Name"
        guest_match = re.search(r'(?:with|interview:?)\s+([^,:\n]+)', item.title, re.I)
        if guest_match:
            metadata['guest'] = guest_match.group(1).strip()
        
        # Try to extract air date from page
        date_elem = soup.find(['time', 'span'], class_=re.compile(r'date|timestamp'))
        if date_elem:
            date_text = date_elem.get_text(strip=True)
            metadata['air_date'] = date_text
        
        return metadata
    
    def _extract_formatted_text(self, content_div) -> str:
        """Extract text while preserving some formatting"""
        # Remove script and style elements
        for element in content_div.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            element.decompose()
        
        # Get text with paragraph breaks
        text_parts = []
        for element in content_div.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'blockquote']):
            text = element.get_text(strip=True)
            if text:
                # Skip common navigation/UI text
                if len(text) < 10 or text.lower() in ['share', 'tweet', 'email', 'print', 'comments']:
                    continue
                
                # Preserve heading markers
                if element.name in ['h1', 'h2', 'h3', 'h4']:
                    text = f"\n## {text}\n"
                text_parts.append(text)
        
        return '\n\n'.join(text_parts)
    
    def _download_audio(self, item: ContentItem, output_dir: str,
                       progress_callback=None) -> Tuple[bool, str]:
        """Download audio file as fallback"""
        if not item.download_url:
            return False, "No audio URL available"
        
        try:
            if progress_callback:
                progress_callback(f"Downloading audio: {item.title}")
            
            response = self.session.get(item.download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Determine file extension
            content_type = response.headers.get('content-type', '')
            ext = '.mp3'
            if 'mp4' in content_type:
                ext = '.mp4'
            elif 'm4a' in content_type:
                ext = '.m4a'
            
            os.makedirs(output_dir, exist_ok=True)
            safe_title = self._safe_filename(item.title)
            audio_path = os.path.join(output_dir, f"{safe_title}{ext}")
            
            # Download with progress
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(audio_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size:
                            percent = (downloaded / total_size) * 100
                            progress_callback(f"Downloading: {percent:.0f}%")
            
            if progress_callback:
                progress_callback(f"✓ Audio saved: {safe_title}")
            
            return True, audio_path
            
        except Exception as e:
            return False, f"Audio download failed: {str(e)}"
    
    def _sanitize_id(self, text: str) -> str:
        """Create a safe ID from text"""
        # Remove special characters, keep alphanumeric and spaces
        safe = re.sub(r'[^\w\s-]', '', text.lower())
        # Replace spaces with underscores
        safe = re.sub(r'[-\s]+', '_', safe)
        # Limit length
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

