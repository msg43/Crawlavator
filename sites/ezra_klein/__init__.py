"""
The Ezra Klein Show Plugin
NYT podcast with transcripts available on nytimes.com
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
class EzraKleinSite(BaseSite):
    """The Ezra Klein Show podcast site plugin"""
    
    SITE_ID = "ezra_klein"
    SITE_NAME = "The Ezra Klein Show"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript", "audio"]
    CATEGORIES = ["podcast"]
    
    BASE_URL = "https://www.nytimes.com"
    RSS_URL = "https://feeds.simplecast.com/82FI35Px"
    
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
            progress_callback("Fetching Ezra Klein Show RSS feed...")
        
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
                    item_id = f"ezra_{slug}"
                    
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
        """Download transcript or audio"""
        try:
            # Try to get transcript from NYT
            response = self.session.get(item.url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Look for transcript on NYT page
            transcript = soup.find(['article', 'div'], class_=re.compile(r'transcript|story-body|article-body'))
            
            if transcript and len(transcript.get_text(strip=True)) > 200:
                os.makedirs(output_dir, exist_ok=True)
                
                safe_title = self._safe_filename(item.title)
                txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
                
                header = f"# {item.title}\n"
                if item.date:
                    header += f"Date: {item.date}\n"
                header += f"Source: The Ezra Klein Show\n\n---\n\n"
                
                transcript_text = transcript.get_text(separator='\n\n', strip=True)
                
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(header + transcript_text)
                
                metadata = {
                    'id': item.id,
                    'title': item.title,
                    'url': item.url,
                    'date': item.date,
                    'source': 'The Ezra Klein Show',
                    'asset_type': 'transcript'
                }
                
                metadata_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2)
                
                return True, "Downloaded transcript"
            
            # Fallback to audio
            if item.download_url:
                return self._download_audio(item, output_dir, progress_callback)
            
            return False, "No transcript or audio found"
            
        except Exception as e:
            if item.download_url:
                return self._download_audio(item, output_dir, progress_callback)
            return False, f"Error: {str(e)}"
    
    def _download_audio(self, item: ContentItem, output_dir: str,
                        progress_callback=None) -> Tuple[bool, str]:
        """Download audio file"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            response = self.session.get(item.download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            ext = '.mp3' if '.mp3' in item.download_url else '.m4a'
            safe_title = self._safe_filename(item.title)
            audio_path = os.path.join(output_dir, f"{safe_title}{ext}")
            
            with open(audio_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return True, f"Downloaded audio ({ext})"
            
        except Exception as e:
            return False, f"Audio error: {str(e)}"
    
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

