"""
Generic Private RSS Feed Plugin
Supports any private RSS feed URL (Sam Harris, Patreon, Supercast, etc.)
"""

import os
import json
import re
import requests
import feedparser
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse

from .. import BaseSite, ContentItem, register_site


@register_site
class PrivateRSSSite(BaseSite):
    """Generic private RSS feed plugin for paid podcasts"""
    
    SITE_ID = "private_rss"
    SITE_NAME = "Private RSS Feeds"
    REQUIRES_AUTH = False  # RSS URLs are pre-authenticated
    ASSET_TYPES = ["audio", "transcript"]
    CATEGORIES = ["private-podcasts"]
    
    def __init__(self):
        self.indexed_content: Dict[str, ContentItem] = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.feeds = []
        self.private_feeds_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            '.private',
            'rss_feeds.json'
        )
    
    def get_config_fields(self) -> List[Dict[str, Any]]:
        # No config needed - feeds managed through UI
        return []
    
    def check_auth(self) -> Tuple[bool, str]:
        # No auth required - RSS URLs are pre-authenticated
        return True, "No authentication required"
    
    def login(self, **credentials) -> Tuple[bool, str]:
        # No auth required
        return True, "No authentication required"
    
    def load_feeds(self) -> List[Dict[str, Any]]:
        """Load private RSS feeds from storage"""
        try:
            if os.path.exists(self.private_feeds_file):
                with open(self.private_feeds_file, 'r') as f:
                    data = json.load(f)
                    return data.get('feeds', [])
        except Exception as e:
            print(f"Error loading private feeds: {e}")
        return []
    
    def index_content(self, progress_callback=None) -> List[ContentItem]:
        """Index all episodes from all private RSS feeds"""
        self.feeds = self.load_feeds()
        
        if not self.feeds:
            if progress_callback:
                progress_callback("No private RSS feeds configured")
            return []
        
        items = []
        
        for feed in self.feeds:
            feed_id = feed.get('id', '')
            feed_name = feed.get('name', 'Unknown Feed')
            feed_url = feed.get('url', '')
            feed_author = feed.get('author', '')
            
            if not feed_url:
                continue
            
            if progress_callback:
                progress_callback(f"Indexing {feed_name}...")
            
            try:
                # Parse RSS feed
                parsed_feed = feedparser.parse(feed_url)
                
                if not parsed_feed.entries:
                    if progress_callback:
                        progress_callback(f"No episodes found in {feed_name}")
                    continue
                
                # Extract episodes
                for entry in parsed_feed.entries:
                    try:
                        item = self._parse_rss_entry(entry, feed_id, feed_name, feed_author)
                        if item and item.id not in self.indexed_content:
                            self.indexed_content[item.id] = item
                            items.append(item)
                    except Exception as e:
                        if progress_callback:
                            progress_callback(f"Error parsing episode: {str(e)}")
                        continue
                
                if progress_callback:
                    progress_callback(f"Indexed {len(items)} episodes from {feed_name}")
                    
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error indexing {feed_name}: {str(e)}")
                continue
        
        return items
    
    def _parse_rss_entry(self, entry, feed_id: str, feed_name: str, 
                         feed_author: str) -> Optional[ContentItem]:
        """Parse an RSS entry into a ContentItem"""
        
        # Extract basic info
        title = entry.get('title', 'Untitled Episode')
        url = entry.get('link', '')
        description = entry.get('summary', '') or entry.get('description', '')
        
        # Extract date
        date_str = ''
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                date_str = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
            except:
                pass
        
        # Extract audio URL from enclosures
        audio_url = None
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enclosure in entry.enclosures:
                if 'audio' in enclosure.get('type', ''):
                    audio_url = enclosure.get('href', '')
                    break
        
        # If no enclosure, check for media:content
        if not audio_url and hasattr(entry, 'media_content'):
            for media in entry.media_content:
                if 'audio' in media.get('type', ''):
                    audio_url = media.get('url', '')
                    break
        
        # Generate unique ID
        # Use guid if available, otherwise create from title
        if hasattr(entry, 'id'):
            entry_id = entry.id
        else:
            entry_id = self._slugify(title)
        
        item_id = f"rss_{feed_id}_{self._slugify(entry_id)}"
        
        return ContentItem(
            id=item_id,
            title=title,  # Don't prepend feed name - it will be in the folder
            url=url,
            asset_type="audio",
            category="podcast",
            subcategory=feed_name,  # Use feed name as subcategory
            date=date_str,
            description=description,
            download_url=audio_url
        )
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download an episode (audio file)"""
        
        if not item.download_url:
            return False, "No audio URL available"
        
        try:
            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            
            # Determine file extension from URL or content type
            ext = '.mp3'
            url_path = urlparse(item.download_url).path
            if url_path.endswith('.m4a'):
                ext = '.m4a'
            elif url_path.endswith('.mp3'):
                ext = '.mp3'
            elif url_path.endswith('.wav'):
                ext = '.wav'
            
            # Create safe filename
            safe_title = self._safe_filename(item.title)
            output_path = os.path.join(output_dir, f"{safe_title}{ext}")
            
            if progress_callback:
                progress_callback(f"Downloading {item.title}...")
            
            # Download audio file
            response = self.session.get(item.download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Check content type for actual format
            content_type = response.headers.get('content-type', '')
            if 'm4a' in content_type or 'mp4' in content_type:
                ext = '.m4a'
                output_path = os.path.join(output_dir, f"{safe_title}{ext}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            progress_callback(f"Downloading {item.title}: {progress}%")
            
            # Save metadata
            metadata = {
                'id': item.id,
                'title': item.title,
                'url': item.url,
                'download_url': item.download_url,
                'date': item.date,
                'description': item.description,
                'source': 'Private RSS Feed',
                'category': item.category,
                'subcategory': item.subcategory
            }
            
            metadata_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            return True, f"Downloaded audio file ({ext})"
            
        except Exception as e:
            return False, f"Download error: {str(e)}"
    
    def _slugify(self, text: str) -> str:
        """Convert text to slug format"""
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '_', text)
        text = text.strip('_')
        return text[:50] if text else 'unknown'
    
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

