"""
Invest Like the Best Podcast Plugin
Hosted by Patrick O'Shaughnessy on joincolossus.com
Downloads transcripts from the website
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
class InvestLikeBestSite(BaseSite):
    """Invest Like the Best podcast site plugin"""
    
    SITE_ID = "invest_like_best"
    SITE_NAME = "Invest Like the Best"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript", "audio"]
    CATEGORIES = ["podcast"]
    
    BASE_URL = "https://www.joincolossus.com"
    RSS_URL = "https://investlikethebest.libsyn.com/rss"
    
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
            progress_callback("Fetching RSS feed...")
        
        try:
            # Parse RSS feed
            feed = feedparser.parse(self.RSS_URL)
            
            if not feed.entries:
                if progress_callback:
                    progress_callback("No episodes found in RSS feed")
                return items
            
            if progress_callback:
                progress_callback(f"Found {len(feed.entries)} episodes, parsing...")
            
            for entry in feed.entries:
                try:
                    # Extract basic info
                    title = entry.get('title', 'Untitled Episode')
                    url = entry.get('link', '')
                    description = entry.get('summary', '')
                    
                    # Extract date
                    date_str = ''
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            date_str = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                        except:
                            pass
                    
                    # Extract audio URL
                    audio_url = None
                    if hasattr(entry, 'enclosures') and entry.enclosures:
                        for enclosure in entry.enclosures:
                            if 'audio' in enclosure.get('type', ''):
                                audio_url = enclosure.get('href', '')
                                break
                    
                    # Extract episode number from title
                    episode_num = None
                    num_match = re.search(r'#(\d+)', title)
                    if num_match:
                        episode_num = num_match.group(1)
                    
                    # Generate ID
                    if episode_num:
                        item_id = f"ilb_{episode_num}"
                    else:
                        slug = self._slugify(title)
                        item_id = f"ilb_{slug}"
                    
                    # Create item with audio as default, transcript will be attempted on download
                    item = ContentItem(
                        id=item_id,
                        title=title,
                        url=url,
                        asset_type="transcript",  # Prefer transcripts
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
                        progress_callback(f"Error parsing episode: {str(e)}")
                    continue
            
            if progress_callback:
                progress_callback(f"Indexed {len(items)} episodes")
            
            return items
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error indexing: {str(e)}")
            return items
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download episode transcript"""
        
        try:
            if progress_callback:
                progress_callback(f"Fetching episode page: {item.title}")
            
            # Try to find transcript on the episode page
            response = self.session.get(item.url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Look for transcript content
            # Colossus typically has transcripts in specific divs or sections
            transcript_content = None
            
            # Strategy 1: Look for transcript section
            transcript_section = soup.find(['div', 'section'], class_=re.compile(r'transcript', re.I))
            if transcript_section:
                transcript_content = transcript_section
            
            # Strategy 2: Look for main content area
            if not transcript_content:
                main_content = soup.find(['article', 'main', 'div'], class_=re.compile(r'content|post|entry'))
                if main_content:
                    transcript_content = main_content
            
            if not transcript_content:
                # Fall back to audio download
                if item.download_url:
                    return self._download_audio(item, output_dir, progress_callback)
                return False, "No transcript or audio found"
            
            # Extract text
            transcript_text = transcript_content.get_text(separator='\n\n', strip=True)
            
            if len(transcript_text) < 100:
                # Transcript too short, try audio
                if item.download_url:
                    return self._download_audio(item, output_dir, progress_callback)
                return False, "Transcript too short"
            
            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            
            # Create safe filename
            safe_title = self._safe_filename(item.title)
            txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
            metadata_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
            
            # Save transcript
            header = f"# {item.title}\n"
            if item.date:
                header += f"Date: {item.date}\n"
            header += f"Source: Invest Like the Best\n"
            header += f"URL: {item.url}\n\n"
            header += "---\n\n"
            
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(header + transcript_text)
            
            # Save metadata
            metadata = {
                'id': item.id,
                'title': item.title,
                'url': item.url,
                'date': item.date,
                'description': item.description,
                'source': 'Invest Like the Best',
                'source_url': 'joincolossus.com',
                'asset_type': 'transcript'
            }
            
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            return True, "Downloaded transcript"
            
        except Exception as e:
            # Try audio fallback
            if item.download_url:
                return self._download_audio(item, output_dir, progress_callback)
            return False, f"Download error: {str(e)}"
    
    def _download_audio(self, item: ContentItem, output_dir: str,
                        progress_callback=None) -> Tuple[bool, str]:
        """Fallback: download audio file"""
        try:
            if progress_callback:
                progress_callback(f"Downloading audio: {item.title}")
            
            os.makedirs(output_dir, exist_ok=True)
            
            response = self.session.get(item.download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Determine file extension
            ext = '.mp3'
            if '.m4a' in item.download_url:
                ext = '.m4a'
            
            safe_title = self._safe_filename(item.title)
            audio_path = os.path.join(output_dir, f"{safe_title}{ext}")
            
            with open(audio_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return True, f"Downloaded audio ({ext})"
            
        except Exception as e:
            return False, f"Audio download error: {str(e)}"
    
    def _slugify(self, text: str) -> str:
        """Convert text to slug"""
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '_', text)
        return text[:50]
    
    def _safe_filename(self, name: str) -> str:
        """Create safe filename"""
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        if len(safe) > 100:
            safe = safe[:100]
        return safe or 'untitled'
    
    def close(self):
        """Clean up resources"""
        self.session.close()

