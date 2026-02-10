"""
Peter Zeihan Podcast Plugin
Public RSS feed with audio downloads
"""

import os
import re
import json
import requests
import feedparser
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from .. import BaseSite, ContentItem, register_site


@register_site
class PeterZeihanSite(BaseSite):
    """Peter Zeihan Podcast site plugin"""
    
    SITE_ID = "peter_zeihan"
    SITE_NAME = "Peter Zeihan Podcast"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["audio"]
    CATEGORIES = ["podcast"]
    
    RSS_URL = "https://media.rss.com/zeihan/feed.xml"
    
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
            progress_callback("Fetching Peter Zeihan RSS feed...")
        
        try:
            feed = feedparser.parse(self.RSS_URL)
            
            if not feed.entries:
                if progress_callback:
                    progress_callback("No episodes found")
                return items
            
            if progress_callback:
                progress_callback(f"Found {len(feed.entries)} episodes")
            
            for entry in feed.entries:
                try:
                    title = entry.get('title', 'Untitled Episode')
                    url = entry.get('link', '')
                    description = entry.get('summary', '')
                    
                    date_str = ''
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            date_str = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                        except:
                            pass
                    
                    audio_url = None
                    if hasattr(entry, 'enclosures') and entry.enclosures:
                        for enclosure in entry.enclosures:
                            if 'audio' in enclosure.get('type', ''):
                                audio_url = enclosure.get('href', '')
                                break
                    
                    slug = self._slugify(title)
                    item_id = f"zeihan_{slug}"
                    
                    item = ContentItem(
                        id=item_id,
                        title=title,
                        url=url,
                        asset_type="audio",
                        category="podcast",
                        subcategory="episodes",
                        date=date_str,
                        description=description,
                        download_url=audio_url
                    )
                    
                    if item.id not in self.indexed_content:
                        self.indexed_content[item.id] = item
                        items.append(item)
                        
                except Exception as e:
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
        """Download audio file"""
        
        if not item.download_url:
            return False, "No audio URL available"
        
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            response = self.session.get(item.download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            ext = '.mp3'
            if '.m4a' in item.download_url:
                ext = '.m4a'
            
            safe_title = self._safe_filename(item.title)
            audio_path = os.path.join(output_dir, f"{safe_title}{ext}")
            
            with open(audio_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            metadata = {
                'id': item.id,
                'title': item.title,
                'url': item.url,
                'date': item.date,
                'source': 'Peter Zeihan Podcast',
                'asset_type': 'audio'
            }
            
            metadata_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            return True, f"Downloaded audio ({ext})"
            
        except Exception as e:
            return False, f"Download error: {str(e)}"
    
    def _slugify(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '_', text)
        return text[:50]
    
    def _safe_filename(self, name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        return safe[:100] if safe else 'untitled'
    
    def close(self):
        self.session.close()

