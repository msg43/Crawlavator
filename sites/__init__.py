"""
Crawlavator Site Plugins
Each site module provides scraping/downloading for a specific website.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class ContentItem:
    """Universal content item across all sites"""
    id: str
    title: str
    url: str
    asset_type: str  # video, pdf, audio, article, transcript
    category: str    # site-specific category
    subcategory: str = ""
    date: str = ""
    description: str = ""
    download_url: Optional[str] = None
    thumbnail: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


class BaseSite(ABC):
    """Abstract base class for all site plugins"""
    
    # Site metadata - override in subclasses
    SITE_ID: str = ""
    SITE_NAME: str = ""
    REQUIRES_AUTH: bool = False
    ASSET_TYPES: List[str] = []
    CATEGORIES: List[str] = []
    
    @abstractmethod
    def get_config_fields(self) -> List[Dict[str, Any]]:
        """
        Return list of config fields for this site.
        Each field: {"id": str, "label": str, "type": str, "required": bool}
        """
        pass
    
    @abstractmethod
    def check_auth(self) -> Tuple[bool, str]:
        """Check if authenticated (for sites requiring login)"""
        pass
    
    @abstractmethod
    def login(self, **credentials) -> Tuple[bool, str]:
        """Login to site (for sites requiring auth)"""
        pass
    
    @abstractmethod
    def index_content(self, progress_callback=None) -> List[ContentItem]:
        """Discover and index all available content"""
        pass
    
    @abstractmethod
    def download_item(self, item: ContentItem, output_dir: str, 
                      progress_callback=None) -> Tuple[bool, str]:
        """Download a single content item"""
        pass
    
    def close(self):
        """Clean up resources"""
        pass


# Registry of available sites
_SITE_REGISTRY: Dict[str, type] = {}


def register_site(site_class: type):
    """Decorator to register a site plugin"""
    _SITE_REGISTRY[site_class.SITE_ID] = site_class
    return site_class


def get_site(site_id: str) -> Optional[type]:
    """Get a site class by ID"""
    return _SITE_REGISTRY.get(site_id)


def get_all_sites() -> Dict[str, type]:
    """Get all registered sites"""
    return _SITE_REGISTRY.copy()


def list_sites() -> List[Dict[str, Any]]:
    """List all sites with metadata"""
    return [
        {
            "id": site_class.SITE_ID,
            "name": site_class.SITE_NAME,
            "requires_auth": site_class.REQUIRES_AUTH,
            "asset_types": site_class.ASSET_TYPES,
            "categories": site_class.CATEGORIES
        }
        for site_class in _SITE_REGISTRY.values()
    ]

