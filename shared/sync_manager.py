"""
Sync Manager - Compare remote content with local downloads and sync new items
"""

import os
import json
import fnmatch
from typing import List, Dict, Any, Set
from datetime import datetime


class SyncManager:
    """Manages synchronization of all sources with local content"""
    
    def __init__(self, download_base_dir: str):
        self.download_base_dir = download_base_dir
        self.sync_log_path = os.path.join(download_base_dir, 'sync_log.jsonl')
    
    def find_local_content(self, source_id: str, search_dir: str = None) -> Set[str]:
        """
        Recursively scan ALL subfolders under search_dir to find existing content IDs
        Returns a set of content IDs that have been downloaded
        
        Args:
            source_id: The source to search for (e.g., 'lexfridman')
            search_dir: Top-level directory to search recursively. 
                       If None, uses self.download_base_dir
        """
        local_ids = set()
        
        # Use provided search directory or default
        if search_dir is None:
            search_dir = self.download_base_dir
        
        # Expand user home directory
        search_dir = os.path.expanduser(search_dir)
        
        if not os.path.exists(search_dir):
            return local_ids
        
        # Strategy 1: Check manifest.json if exists in the base directory
        manifest_path = os.path.join(self.download_base_dir, 'manifest.json')
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                    completed = manifest.get('completed', {})
                    for item_id in completed.keys():
                        if item_id.startswith(source_id):
                            local_ids.add(item_id)
            except Exception as e:
                print(f"Error reading manifest: {e}")
        
        # Strategy 2: Recursively scan ALL subfolders under search_dir
        print(f"Scanning {search_dir} for {source_id} content...")
        
        # Track which IDs have transcripts vs audio
        transcript_ids = set()
        audio_ids = set()
        
        for root, dirs, files in os.walk(search_dir):
            for file in files:
                file_lower = file.lower()
                
                # Check if filename contains source identifier
                if source_id.lower().replace('_', '') not in file_lower.replace('_', ''):
                    continue
                
                # Determine file type and extract ID
                if file.endswith('_transcript.txt'):
                    # Extract ID from transcript filename
                    base_name = file.replace('_transcript.txt', '')
                    parts = base_name.split('_')
                    if len(parts) >= 2:
                        potential_id = '_'.join(parts[:3]) if len(parts) >= 3 else '_'.join(parts[:2])
                        if potential_id and len(potential_id) > 3:
                            transcript_ids.add(potential_id)
                            local_ids.add(potential_id)  # Has content (transcript)
                
                elif file.endswith(('.mp3', '.m4a', '.wav', '.mp4')):
                    # Extract ID from audio/video filename
                    # Remove extension
                    for ext in ['.mp3', '.m4a', '.wav', '.mp4']:
                        if file.endswith(ext):
                            base_name = file[:-len(ext)]
                            break
                    
                    parts = base_name.split('_')
                    if len(parts) >= 2:
                        potential_id = '_'.join(parts[:3]) if len(parts) >= 3 else '_'.join(parts[:2])
                        if potential_id and len(potential_id) > 3:
                            audio_ids.add(potential_id)
                            # Only add to local_ids if we don't already have transcript
                            # (prefer transcript over audio for transcript-first sources)
                            if potential_id not in transcript_ids:
                                local_ids.add(potential_id)
        
        print(f"Found {len(transcript_ids)} transcripts and {len(audio_ids)} audio files for {source_id}")
        print(f"Total {len(local_ids)} unique items already downloaded")
        return local_ids
    
    def compare_with_remote(self, indexed_items: List[Any], local_ids: Set[str]) -> List[Any]:
        """
        Compare indexed remote content with local content
        Returns list of items that need to be downloaded
        """
        new_items = []
        
        for item in indexed_items:
            if item.id not in local_ids:
                new_items.append(item)
        
        return new_items
    
    def sync_source(self, source_id: str, source_name: str, 
                    indexed_items: List[Any], search_dir: str = None) -> Dict[str, Any]:
        """
        Sync a single source
        Returns statistics about the sync operation
        
        Args:
            source_id: Source identifier
            source_name: Display name of source
            indexed_items: List of ContentItem objects from indexing
            search_dir: Top-level directory to search recursively
        """
        # Find what we already have locally
        local_ids = self.find_local_content(source_id, search_dir)
        
        # Determine what's new
        new_items = self.compare_with_remote(indexed_items, local_ids)
        
        return {
            'source': source_id,
            'source_name': source_name,
            'indexed': len(indexed_items),
            'local': len(local_ids),
            'new': len(new_items),
            'new_items_preview': [{'id': item.id, 'title': item.title} for item in new_items[:10]],  # Limit to first 10 for preview
            'new_items_full': new_items  # Return full ContentItem objects for downloading
        }
    
    def log_sync_operation(self, results: Dict[str, Any]):
        """
        Log sync operation to JSONL file
        Each line is a complete JSON object representing one sync operation
        """
        try:
            os.makedirs(os.path.dirname(self.sync_log_path), exist_ok=True)
            
            # Build detailed source breakdown
            source_summary = []
            for detail in results.get('details', []):
                source_summary.append({
                    'source': detail.get('source_name', detail.get('source', 'unknown')),
                    'indexed': detail.get('indexed', 0),
                    'local': detail.get('local', 0),
                    'new_available': detail.get('new', 0),
                    'downloaded': detail.get('downloaded', 0),
                    'download_errors': detail.get('download_errors', 0),
                    'error': detail.get('error', None)
                })
            
            log_entry = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'operation': 'sync_all',
                'search_directory': results.get('search_dir', 'unknown'),
                'sources_checked': results.get('sources_checked', 0),
                'total_downloaded': results.get('new_items', 0),
                'total_skipped': results.get('skipped', 0),
                'total_errors': results.get('errors', 0),
                'duration_seconds': results.get('duration_seconds', 0),
                'source_details': source_summary
            }
            
            # Append to JSONL file (one JSON object per line)
            with open(self.sync_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            print(f"\n✓ Sync log written to: {self.sync_log_path}")
                
        except Exception as e:
            print(f"Error logging sync operation: {e}")
    
    def get_recent_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sync log entries"""
        logs = []
        
        if not os.path.exists(self.sync_log_path):
            return logs
        
        try:
            with open(self.sync_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Get last N lines
                for line in lines[-limit:]:
                    try:
                        logs.append(json.loads(line))
                    except:
                        continue
        except Exception as e:
            print(f"Error reading sync logs: {e}")
        
        return logs
    
    def is_content_downloaded(self, content_id: str, content_title: str, 
                               download_dir: str) -> bool:
        """
        Check if specific content already exists locally
        Uses multiple strategies to detect existing content
        """
        # Strategy 1: Check manifest.json
        manifest_path = os.path.join(self.download_base_dir, 'manifest.json')
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                    if content_id in manifest.get('completed', {}):
                        return True
            except:
                pass
        
        # Strategy 2: Look for files matching ID or title
        if os.path.exists(download_dir):
            safe_title = self._safe_filename(content_title)
            patterns = [
                f"*{content_id}*",
                f"*{safe_title}*"
            ]
            
            for root, dirs, files in os.walk(download_dir):
                for pattern in patterns:
                    matches = fnmatch.filter(files, pattern)
                    if matches:
                        return True
        
        return False
    
    def _safe_filename(self, name: str) -> str:
        """Convert string to safe filename"""
        import re
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        return safe[:50] if safe else 'unknown'

