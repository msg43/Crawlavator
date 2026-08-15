"""
Eurodollar University Site Plugin
Downloads member content, DDA articles, and Daily Briefings
"""

import os
import json
import time
from typing import List, Dict, Any, Optional, Tuple

from .. import BaseSite, ContentItem, register_site
from .auth import EDUAuth
from .scraper import EDUScraper


@register_site
class EurodollarSite(BaseSite):
    """Eurodollar University site plugin"""
    
    SITE_ID = "eurodollar"
    SITE_NAME = "Eurodollar University"
    REQUIRES_AUTH = True
    ASSET_TYPES = ["video", "article", "pdf", "audio", "transcript"]
    CATEGORIES = ["membership", "dda", "daily-briefing"]
    IMPORT_SOURCE = "eurodollaruniversity.com"
    
    def __init__(self):
        self.auth = EDUAuth()
        self.scraper = None
        self.indexed_content: Dict[str, ContentItem] = {}
    
    def get_config_fields(self) -> List[Dict[str, Any]]:
        return [
            {"id": "email", "label": "Email", "type": "email", "required": True},
            {"id": "password", "label": "Password", "type": "password", "required": True},
        ]
    
    def check_auth(self) -> Tuple[bool, str]:
        return self.auth.check_auth_status()
    
    def login(self, email: str = "", password: str = "", interactive: bool = False, **kwargs) -> Tuple[bool, str]:
        if interactive:
            return self.auth.login_interactive()
        return self.auth.login(email, password, headless=False)
    
    def index_content(self, progress_callback=None) -> List[ContentItem]:
        """Index all EDU content"""
        self.scraper = EDUScraper(self.auth)
        results = self.scraper.index_all(progress_callback)
        
        # Convert to universal ContentItem format
        items = []
        for item in self.scraper.get_all_items():
            content_item = ContentItem(
                id=item.id,
                title=item.title,
                url=item.url,
                asset_type=item.asset_type,
                category=item.category,
                subcategory=item.subcategory,
                date=item.date,
                description=item.description,
                download_url=item.download_url,
                thumbnail=item.thumbnail
            )
            items.append(content_item)
            self.indexed_content[item.id] = content_item
        
        return items
    
    def get_summary(self) -> Dict[str, Any]:
        """Get indexing summary"""
        if self.scraper:
            return self.scraper.get_summary()
        return {"total_items": 0}
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download a single content item with metadata sidecar"""
        # Import downloaders
        from .downloaders import VideoExtractor, ArticleDownloader, PDFDownloader
        
        video_extractor = VideoExtractor(self.auth)
        article_dl = ArticleDownloader(self.auth)
        pdf_dl = PDFDownloader(self.auth)
        
        try:
            asset_type = item.asset_type
            success = False
            message = ""
            
            if asset_type == 'video':
                output_path = os.path.join(output_dir, 'video.mp4')
                success, message = video_extractor.download_video(item.url, output_path, progress_callback)
            
            elif asset_type == 'article':
                success, message = article_dl.download_article(item.url, output_dir)
            
            elif asset_type == 'pdf':
                if item.download_url:
                    output_path = os.path.join(output_dir, f"{self._safe_filename(item.title)}.pdf")
                    success, message = pdf_dl.download_file(item.download_url, output_path)
                else:
                    success, message = pdf_dl.download_daily_briefing(item.url, item.title, output_dir)
            
            elif asset_type == 'audio':
                if item.download_url:
                    ext = '.m4a'
                    for e in ['.m4a', '.mp3', '.wav']:
                        if e in item.download_url.lower():
                            ext = e
                            break
                    output_path = os.path.join(output_dir, f"{self._safe_filename(item.title)}{ext}")
                    success, message = pdf_dl.download_file(item.download_url, output_path)
                else:
                    return False, "No download URL for audio"
            
            elif asset_type == 'transcript':
                success, message = article_dl.download_transcript(item.url, item.title, output_dir)
            
            else:
                return False, f"Unknown asset type: {asset_type}"
            
            # Write metadata sidecar on successful download
            if success:
                self._write_metadata_sidecar(item, output_dir)
            
            return success, message
                
        except Exception as e:
            return False, str(e)
    
    def _write_metadata_sidecar(self, item: ContentItem, output_dir: str):
        """Write a normalized metadata.json sidecar for any downloaded item"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            safe_title = self._safe_filename(item.title)
            
            raw_metadata = {
                'id': item.id,
                'title': item.title,
                'url': item.url,
                'date': item.date,
                'description': item.description,
                'source': 'Eurodollar University',
                'asset_type': item.asset_type,
            }
            normalized = self.build_normalized_metadata(
                raw_metadata,
                has_diarization=False,
                has_segments=False,
                segment_count=0,
            )
            
            metadata_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(normalized, f, indent=2)
        except Exception:
            pass  # Don't fail the download if metadata write fails
    
    def _safe_filename(self, name: str) -> str:
        import re
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        if len(safe) > 100:
            safe = safe[:100]
        return safe or 'untitled'
    
    def close(self):
        if self.auth:
            self.auth.close()

