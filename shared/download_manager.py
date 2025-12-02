"""
Download Manager
Handles download tracking, resume logic, and manifest management
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class DownloadStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"
    RESTRICTED = "restricted"


@dataclass
class DownloadEntry:
    """Represents a single download item in the manifest"""
    id: str
    title: str
    url: str
    asset_type: str  # video, pdf, audio, article, transcript
    category: str    # membership, dda, daily-briefing
    status: str = "pending"
    local_path: Optional[str] = None
    size: Optional[int] = None
    expected_size: Optional[int] = None
    resume_position: Optional[int] = None
    checksum: Optional[str] = None
    downloaded_at: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DownloadEntry':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AccessLogEntry:
    """Represents an access log entry for restricted content"""
    url: str
    title: str
    reason: str
    timestamp: str


class DownloadManager:
    """Manages download tracking, resume logic, and manifest"""
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.manifest_path = os.path.join(base_dir, 'manifest.json')
        self.access_log_path = os.path.join(base_dir, 'access_log.json')
        
        os.makedirs(base_dir, exist_ok=True)
        
        self.manifest = self._load_manifest()
        self.access_log = self._load_access_log()
    
    def _load_manifest(self) -> Dict[str, Any]:
        """Load manifest from file or create new"""
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        return {
            "created_at": datetime.now().isoformat(),
            "last_sync": None,
            "downloads": {}
        }
    
    def _save_manifest(self):
        """Save manifest to file"""
        self.manifest["last_sync"] = datetime.now().isoformat()
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)
    
    def _load_access_log(self) -> Dict[str, Any]:
        """Load access log from file or create new"""
        if os.path.exists(self.access_log_path):
            try:
                with open(self.access_log_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        return {
            "accessible": [],
            "restricted": [],
            "errors": []
        }
    
    def _save_access_log(self):
        """Save access log to file"""
        with open(self.access_log_path, 'w', encoding='utf-8') as f:
            json.dump(self.access_log, f, indent=2, ensure_ascii=False)
    
    def get_download_status(self, item_id: str) -> Optional[DownloadEntry]:
        """Get the download status for an item"""
        if item_id in self.manifest["downloads"]:
            return DownloadEntry.from_dict(self.manifest["downloads"][item_id])
        return None
    
    def should_download(self, item_id: str, expected_size: Optional[int] = None) -> bool:
        """
        Check if an item should be downloaded.
        Returns False if already complete, True otherwise.
        """
        entry = self.get_download_status(item_id)
        
        if not entry:
            return True
        
        if entry.status == DownloadStatus.COMPLETE.value:
            # Verify file still exists
            if entry.local_path and os.path.exists(entry.local_path):
                # If we have expected size, verify
                if expected_size and entry.size:
                    if entry.size >= expected_size * 0.98:  # Allow 2% tolerance
                        return False
                elif entry.size and entry.size > 0:
                    return False
            # File missing, need to re-download
            return True
        
        if entry.status in [DownloadStatus.FAILED.value, DownloadStatus.RESTRICTED.value]:
            return False  # Don't retry failed/restricted
        
        return True
    
    def get_resume_position(self, item_id: str) -> int:
        """Get the resume position for a partial download"""
        entry = self.get_download_status(item_id)
        if entry and entry.status == DownloadStatus.PARTIAL.value:
            return entry.resume_position or 0
        return 0
    
    def start_download(self, item_id: str, title: str, url: str, 
                       asset_type: str, category: str, local_path: str):
        """Mark a download as started"""
        entry = DownloadEntry(
            id=item_id,
            title=title,
            url=url,
            asset_type=asset_type,
            category=category,
            status=DownloadStatus.IN_PROGRESS.value,
            local_path=local_path
        )
        self.manifest["downloads"][item_id] = entry.to_dict()
        self._save_manifest()
    
    def update_progress(self, item_id: str, bytes_downloaded: int, expected_size: Optional[int] = None):
        """Update download progress (for resume capability)"""
        if item_id in self.manifest["downloads"]:
            self.manifest["downloads"][item_id]["size"] = bytes_downloaded
            self.manifest["downloads"][item_id]["resume_position"] = bytes_downloaded
            if expected_size:
                self.manifest["downloads"][item_id]["expected_size"] = expected_size
            self.manifest["downloads"][item_id]["status"] = DownloadStatus.PARTIAL.value
            # Don't save on every update - too slow
    
    def complete_download(self, item_id: str, local_path: str, size: int, checksum: Optional[str] = None):
        """Mark a download as complete"""
        if item_id in self.manifest["downloads"]:
            self.manifest["downloads"][item_id].update({
                "status": DownloadStatus.COMPLETE.value,
                "local_path": local_path,
                "size": size,
                "checksum": checksum,
                "downloaded_at": datetime.now().isoformat(),
                "error": None
            })
        else:
            entry = DownloadEntry(
                id=item_id,
                title=item_id,
                url="",
                asset_type="unknown",
                category="unknown",
                status=DownloadStatus.COMPLETE.value,
                local_path=local_path,
                size=size,
                checksum=checksum,
                downloaded_at=datetime.now().isoformat()
            )
            self.manifest["downloads"][item_id] = entry.to_dict()
        
        self._save_manifest()
    
    def fail_download(self, item_id: str, error: str):
        """Mark a download as failed"""
        if item_id in self.manifest["downloads"]:
            self.manifest["downloads"][item_id].update({
                "status": DownloadStatus.FAILED.value,
                "error": error
            })
            self._save_manifest()
        
        self.access_log["errors"].append({
            "id": item_id,
            "error": error,
            "timestamp": datetime.now().isoformat()
        })
        self._save_access_log()
    
    def mark_restricted(self, item_id: str, title: str, url: str, reason: str):
        """Mark content as restricted (access denied)"""
        if item_id in self.manifest["downloads"]:
            self.manifest["downloads"][item_id].update({
                "status": DownloadStatus.RESTRICTED.value,
                "error": reason
            })
        else:
            entry = DownloadEntry(
                id=item_id,
                title=title,
                url=url,
                asset_type="unknown",
                category="unknown",
                status=DownloadStatus.RESTRICTED.value,
                error=reason
            )
            self.manifest["downloads"][item_id] = entry.to_dict()
        
        self._save_manifest()
        
        self.access_log["restricted"].append({
            "id": item_id,
            "title": title,
            "url": url,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        self._save_access_log()
    
    def mark_accessible(self, url: str, title: str):
        """Log successful access to content"""
        self.access_log["accessible"].append({
            "url": url,
            "title": title,
            "timestamp": datetime.now().isoformat()
        })
    
    def skip_download(self, item_id: str, reason: str = "Already exists"):
        """Mark a download as skipped"""
        if item_id in self.manifest["downloads"]:
            self.manifest["downloads"][item_id]["status"] = DownloadStatus.SKIPPED.value
            self.manifest["downloads"][item_id]["error"] = reason
    
    def get_summary(self) -> Dict[str, int]:
        """Get summary statistics"""
        stats = {
            "total": 0,
            "complete": 0,
            "partial": 0,
            "failed": 0,
            "restricted": 0,
            "pending": 0,
            "skipped": 0
        }
        
        for entry in self.manifest["downloads"].values():
            stats["total"] += 1
            status = entry.get("status", "pending")
            if status in stats:
                stats[status] += 1
        
        return stats
    
    def get_new_since(self, since_date: Optional[str] = None) -> List[str]:
        """Get list of item IDs that are new since the given date"""
        if not since_date:
            since_date = self.manifest.get("last_sync")
        
        if not since_date:
            return []  # First sync, everything is new
        
        new_items = []
        for item_id, entry in self.manifest["downloads"].items():
            if entry.get("downloaded_at"):
                if entry["downloaded_at"] > since_date:
                    new_items.append(item_id)
        
        return new_items
    
    def calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return f"sha256:{sha256.hexdigest()}"
    
    def save(self):
        """Explicitly save both manifest and access log"""
        self._save_manifest()
        self._save_access_log()

