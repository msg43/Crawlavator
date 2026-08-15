"""
Crawlavator Site Plugins
Each site module provides scraping/downloading for a specific website.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


CRAWLAVATOR_VERSION = "1.1.0"


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


def normalize_metadata(
    raw_metadata: Dict[str, Any],
    *,
    site_id: str,
    site_name: str,
    import_source: str,
    has_diarization: bool = False,
    has_segments: bool = False,
    segment_count: int = 0,
    participants: Optional[List[Dict[str, str]]] = None,
    tags: Optional[List[str]] = None,
    youtube_video_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalize any site-specific metadata dict into the canonical crawlavator schema.

    The canonical fields are pulled out; everything else is preserved verbatim
    inside the ``site_metadata`` sub-object so nothing is ever lost.

    Parameters
    ----------
    raw_metadata : dict
        The original metadata dict produced by the site plugin.
    site_id : str
        The SITE_ID of the plugin (e.g. ``"conversationswithtyler"``).
    site_name : str
        Human-readable name (e.g. ``"Conversations with Tyler"``).
    import_source : str
        Domain or identifier of the upstream source (e.g. ``"conversationswithtyler.com"``).
    has_diarization : bool
        Whether the transcript has verified speaker diarization.
    has_segments : bool
        Whether a segments.json file was generated.
    segment_count : int
        Number of segments (0 if none).
    participants : list or None
        List of ``{"name": ..., "role": "host"|"guest"}`` dicts.
    tags : list or None
        Topic tags extracted from the episode.
    youtube_video_id : str or None
        YouTube video ID if discoverable.
    """

    # Canonical fields we pull out of raw_metadata (the rest stays in site_metadata)
    CANONICAL_KEYS = {
        "id", "title", "date", "url", "source", "source_url",
        "description", "asset_type", "segment_count",
    }

    canonical: Dict[str, Any] = {
        "id": raw_metadata.get("id", ""),
        "title": raw_metadata.get("title", ""),
        "date": raw_metadata.get("date", ""),
        "url": raw_metadata.get("url", ""),
        "source": raw_metadata.get("source", site_name),
        "source_url": raw_metadata.get("source_url", ""),
        "description": raw_metadata.get("description", ""),
        "participants": participants or [],
        "tags": tags or [],
        "asset_type": raw_metadata.get("asset_type", "transcript"),
        "has_diarization": has_diarization,
        "has_segments": has_segments,
        "segment_count": segment_count,
        "youtube_video_id": youtube_video_id,
        "provenance": {
            "producer_app": "crawlavator",
            "version": CRAWLAVATOR_VERSION,
            "import_source": import_source,
            "scrape_date": datetime.utcnow().strftime("%Y-%m-%d"),
        },
    }

    # Everything that is NOT a canonical key goes into site_metadata
    site_metadata: Dict[str, Any] = {}
    for key, value in raw_metadata.items():
        if key not in CANONICAL_KEYS and key != "provenance":
            site_metadata[key] = value
    canonical["site_metadata"] = site_metadata

    return canonical


class BaseSite(ABC):
    """Abstract base class for all site plugins"""
    
    # Site metadata - override in subclasses
    SITE_ID: str = ""
    SITE_NAME: str = ""
    REQUIRES_AUTH: bool = False
    ASSET_TYPES: List[str] = []
    CATEGORIES: List[str] = []
    
    # Override in subclasses that know their import domain
    IMPORT_SOURCE: str = ""
    
    def build_normalized_metadata(
        self,
        raw_metadata: Dict[str, Any],
        *,
        has_diarization: bool = False,
        has_segments: bool = False,
        segment_count: int = 0,
        participants: Optional[List[Dict[str, str]]] = None,
        tags: Optional[List[str]] = None,
        youtube_video_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience wrapper around the module-level normalize_metadata()."""
        return normalize_metadata(
            raw_metadata,
            site_id=self.SITE_ID,
            site_name=self.SITE_NAME,
            import_source=self.IMPORT_SOURCE or self.SITE_ID,
            has_diarization=has_diarization,
            has_segments=has_segments,
            segment_count=segment_count,
            participants=participants,
            tags=tags,
            youtube_video_id=youtube_video_id,
        )
    
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

