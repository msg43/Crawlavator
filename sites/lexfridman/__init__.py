"""
Lex Fridman Podcast Site Plugin
Downloads transcripts from lexfridman.com and converts to knowledge_chipper format
"""

import os
import re
import json
import requests
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .. import BaseSite, ContentItem, register_site


@register_site
class LexFridmanSite(BaseSite):
    """Lex Fridman Podcast site plugin"""
    
    SITE_ID = "lexfridman"
    SITE_NAME = "Lex Fridman Podcast"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript"]
    CATEGORIES = ["podcast"]
    
    BASE_URL = "https://lexfridman.com"
    PODCAST_URL = "https://lexfridman.com/podcast"
    
    def __init__(self):
        self.indexed_content: Dict[str, ContentItem] = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def get_config_fields(self) -> List[Dict[str, Any]]:
        # No config needed - public site
        return []
    
    def check_auth(self) -> Tuple[bool, str]:
        # No auth required
        return True, "No authentication required"
    
    def login(self, **credentials) -> Tuple[bool, str]:
        # No auth required
        return True, "No authentication required"
    
    def index_content(self, progress_callback=None) -> List[ContentItem]:
        """Discover all transcripts from lexfridman.com/podcast"""
        items = []
        
        if progress_callback:
            progress_callback("Fetching podcast page...")
        
        try:
            # Get the main podcast page
            response = self.session.get(self.PODCAST_URL, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Find all transcript links
            transcript_links = soup.find_all('a', href=re.compile(r'-transcript$'))
            
            if progress_callback:
                progress_callback(f"Found {len(transcript_links)} transcript links, parsing...")
            
            seen_urls = set()
            
            for link in transcript_links:
                href = link.get('href', '')
                if not href or href in seen_urls:
                    continue
                
                seen_urls.add(href)
                
                # Make absolute URL
                full_url = urljoin(self.BASE_URL, href)
                
                # Extract episode info from URL
                # Pattern: /guest-name-transcript or /guest-name-N-transcript
                slug = href.replace('-transcript', '').strip('/')
                
                # Get title from nearby elements - look for the episode title link
                title = None
                episode_num = None
                
                # The transcript link is usually in a container with the episode info
                # Look for nearby links that point to the episode page or YouTube
                parent = link.find_parent(['div', 'li', 'section', 'generic'])
                
                if parent:
                    # Look for links that might be episode titles (not the transcript link itself)
                    episode_links = parent.find_all('a')
                    for ep_link in episode_links:
                        ep_href = ep_link.get('href', '')
                        ep_text = ep_link.get_text(strip=True)
                        
                        # Skip transcript links, video links, and generic nav
                        if '-transcript' in ep_href or 'youtube.com' in ep_href:
                            continue
                        if ep_text.lower() in ['transcript', 'video', 'episode', '']:
                            continue
                        
                        # This might be the episode title
                        if len(ep_text) > 10:  # Reasonable title length
                            title = ep_text
                            # Extract episode number from title
                            num_match = re.search(r'#(\d+)', title)
                            if num_match:
                                episode_num = num_match.group(1)
                            break
                    
                    # Also check for person/description spans
                    if not title:
                        spans = parent.find_all(['span', 'div'])
                        for span in spans:
                            span_text = span.get_text(strip=True)
                            if len(span_text) > 20 and not span_text.lower().startswith(('video', 'transcript', 'episode')):
                                # Could be a title or description
                                title = span_text[:100]
                                break
                
                # Fallback: use slug as title
                if not title or title.lower() == 'transcript':
                    title = slug.replace('-', ' ').title()
                    # Try to make it nicer
                    title = re.sub(r'(\d+)$', r'#\1', title)  # Add # before trailing numbers
                
                # Clean up title - remove URL prefixes if present
                title = re.sub(r'^https?://[^/]+/', '', title, flags=re.IGNORECASE)
                title = title.strip()
                
                # Generate ID
                if episode_num:
                    item_id = f"lex_{episode_num}_{slug}"
                else:
                    item_id = f"lex_{slug}"
                
                item = ContentItem(
                    id=item_id,
                    title=title,
                    url=full_url,
                    asset_type="transcript",
                    category="podcast",
                    subcategory="transcripts",
                    description=f"Episode #{episode_num}" if episode_num else ""
                )
                
                if item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)
            
            if progress_callback:
                progress_callback(f"Indexed {len(items)} transcripts")
            
            return items
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error indexing: {str(e)}")
            return items
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download a transcript and parse to segments"""
        os.makedirs(output_dir, exist_ok=True)
        
        txt_path = os.path.join(output_dir, 'transcript.txt')
        segments_path = os.path.join(output_dir, 'segments.json')
        metadata_path = os.path.join(output_dir, 'metadata.json')
        
        try:
            # Fetch transcript page
            response = self.session.get(item.url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Extract title
            title_elem = soup.find('h1')
            title = title_elem.get_text(strip=True) if title_elem else item.title
            
            # Extract episode number from title
            episode_num = None
            num_match = re.search(r'#(\d+)', title)
            if num_match:
                episode_num = num_match.group(1)
            
            # Parse segments with timestamps
            raw_segments = self._parse_transcript_segments(soup, item.id, title)
            
            # Save plain text transcript
            plain_text = self._segments_to_text(raw_segments, title)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)
            
            # Build knowledge_chipper compatible format with episode context
            episode_id = f"lex_fridman_{episode_num}" if episode_num else item.id
            
            # Clean up title for episode_title (remove "Transcript for" prefix if present)
            episode_title = re.sub(r'^Transcript\s+for\s+', '', title, flags=re.IGNORECASE)
            
            # Wrap each segment with context (miner_input.v1.json format)
            miner_inputs = []
            for i, seg in enumerate(raw_segments):
                miner_input = {
                    "segment": seg,
                    "context": {
                        "episode_id": episode_id,
                        "episode_title": episode_title,
                        "source": "Lex Fridman Podcast",
                        "source_url": item.url,
                        # Knowledge Chipper tracking fields
                        "source_type": "crawlavator",  # Identifies ingestion method
                        "ingestion_method": "crawlavator_import",
                        "original_source_type": "podcast_transcript"
                    },
                    "provenance": {
                        "producer_app": "crawlavator",
                        "version": "1.0.0",
                        "import_source": "lexfridman.com"
                    }
                }
                # Add previous segments for context (last 2)
                if i > 0:
                    prev_segs = []
                    for j in range(max(0, i-2), i):
                        prev_segs.append({
                            "segment_id": raw_segments[j]["segment_id"],
                            "speaker": raw_segments[j]["speaker"],
                            "text": raw_segments[j]["text"][:200] + "..." if len(raw_segments[j]["text"]) > 200 else raw_segments[j]["text"]
                        })
                    miner_input["context"]["previous_segments"] = prev_segs
                
                miner_inputs.append(miner_input)
            
            # Save segments JSON (knowledge_chipper miner_input.v1.json format)
            with open(segments_path, 'w', encoding='utf-8') as f:
                json.dump(miner_inputs, f, indent=2, ensure_ascii=False)
            
            # Save metadata
            metadata = {
                'id': item.id,
                'episode_id': episode_id,
                'title': title,
                'episode_title': episode_title,
                'url': item.url,
                'episode_number': episode_num,
                'segment_count': len(raw_segments),
                'source': 'Lex Fridman Podcast',
                'source_url': 'lexfridman.com',
                # Knowledge Chipper tracking
                'source_type': 'crawlavator',
                'ingestion_method': 'crawlavator_import',
                'original_source_type': 'podcast_transcript',
                'provenance': {
                    'producer_app': 'crawlavator',
                    'version': '1.0.0',
                    'import_source': 'lexfridman.com'
                }
            }
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            return True, f"Saved {len(segments)} segments"
            
        except Exception as e:
            return False, f"Download error: {str(e)}"
    
    def _parse_transcript_segments(self, soup: BeautifulSoup, episode_id: str, title: str) -> List[Dict]:
        """Parse transcript HTML into knowledge_chipper segments"""
        segments = []
        
        # Find the main content area
        content = soup.select_one('article, main, .entry-content, .post-content')
        if not content:
            content = soup.find('body')
        
        if not content:
            return segments
        
        # Extract chapter headings for topic hints
        chapter_map = {}  # timestamp -> chapter name
        chapter_links = content.find_all('a', href=re.compile(r'#chapter'))
        for ch_link in chapter_links:
            ch_text = ch_link.get_text(strip=True)
            ts_match = re.search(r'^(\d{1,2}:\d{2}(?::\d{2})?)\s*[–-]\s*(.+)', ch_text)
            if ts_match:
                ts = ts_match.group(1)
                # Normalize to HH:MM:SS
                parts = ts.split(':')
                if len(parts) == 2:
                    ts = f"00:{parts[0].zfill(2)}:{parts[1].zfill(2)}"
                elif len(parts) == 3:
                    ts = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
                chapter_map[ts] = ts_match.group(2).strip()
        
        segment_idx = 0
        current_speaker = "Unknown"
        current_chapter = None
        
        # Find timestamp links (Lex format: <a href="...?t=seconds">(HH:MM:SS)</a>)
        timestamp_links = content.find_all('a', href=re.compile(r'[?&]t=\d+'))
        
        for ts_link in timestamp_links:
            try:
                # Get timestamp
                ts_text = ts_link.get_text(strip=True)
                ts_match = re.search(r'\((\d{2}:\d{2}:\d{2})\)', ts_text)
                if not ts_match:
                    continue
                
                timestamp = ts_match.group(1)
                
                # Check if this timestamp starts a new chapter
                if timestamp in chapter_map:
                    current_chapter = chapter_map[timestamp]
                
                # Get speaker - look in parent container
                parent = ts_link.parent
                if parent:
                    # The speaker is usually the first child element before the timestamp
                    for child in parent.children:
                        if hasattr(child, 'get_text'):
                            child_text = child.get_text(strip=True)
                            # Check if it's a speaker name (not timestamp, not too long)
                            if (child_text and 
                                len(child_text) < 50 and 
                                not child_text.startswith('(') and
                                child_text not in ['', 'Transcript']):
                                current_speaker = child_text
                                break
                
                # Get text content (after timestamp link)
                text_parts = []
                for sibling in ts_link.next_siblings:
                    if hasattr(sibling, 'name'):
                        # Stop if we hit another timestamp link
                        if sibling.name == 'a' and sibling.get('href') and 't=' in sibling.get('href', ''):
                            break
                        text = sibling.get_text(strip=True)
                    else:
                        text = str(sibling).strip()
                    
                    if text:
                        text_parts.append(text)
                
                segment_text = ' '.join(text_parts).strip()
                
                if not segment_text:
                    continue
                
                segment = {
                    'segment_id': f"{episode_id}_seg_{segment_idx:04d}",
                    'speaker': current_speaker,
                    'timestamp_start': timestamp,
                    'timestamp_end': timestamp,  # Will be fixed in second pass
                    'text': segment_text
                }
                
                # Add topic hint if available
                if current_chapter:
                    segment['topic_guess'] = current_chapter
                
                segments.append(segment)
                segment_idx += 1
                
            except Exception:
                continue
        
        # Second pass: calculate end timestamps from next segment's start
        for i in range(len(segments) - 1):
            segments[i]['timestamp_end'] = segments[i + 1]['timestamp_start']
        
        # For the last segment, estimate 60 seconds duration
        if segments:
            last_start = segments[-1]['timestamp_start']
            h, m, s = map(int, last_start.split(':'))
            end_seconds = h * 3600 + m * 60 + s + 60
            end_h = end_seconds // 3600
            end_m = (end_seconds % 3600) // 60
            end_s = end_seconds % 60
            segments[-1]['timestamp_end'] = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"
        
        # If no segments found with timestamp links, try alternative parsing
        if not segments:
            segments = self._parse_transcript_fallback(content, episode_id)
        
        return segments
    
    def _parse_transcript_fallback(self, content, episode_id: str) -> List[Dict]:
        """Fallback parser when timestamp links aren't found"""
        segments = []
        
        # Get all text content, split by speaker changes
        text = content.get_text(separator='\n', strip=True)
        
        # Split by common speaker patterns
        speaker_pattern = re.compile(r'\n((?:Lex Fridman|[A-Z][a-z]+ [A-Z][a-z]+)):?\s*', re.MULTILINE)
        
        parts = speaker_pattern.split(text)
        
        current_speaker = "Unknown"
        segment_idx = 0
        
        for i, part in enumerate(parts):
            if not part.strip():
                continue
            
            # Check if this is a speaker name
            if speaker_pattern.match('\n' + part + ':'):
                current_speaker = part
                continue
            
            # This is content
            segment = {
                'segment_id': f"{episode_id}_seg_{segment_idx:04d}",
                'speaker': current_speaker,
                'timestamp_start': "00:00:00",
                'timestamp_end': "00:00:00",
                'text': part.strip()[:2000]  # Limit segment length
            }
            
            if len(segment['text']) > 50:  # Only add substantial segments
                segments.append(segment)
                segment_idx += 1
        
        return segments
    
    def _segments_to_text(self, segments: List[Dict], title: str) -> str:
        """Convert segments to plain text transcript"""
        lines = [f"# {title}\n\n"]
        
        current_speaker = None
        
        for seg in segments:
            speaker = seg.get('speaker', 'Unknown')
            ts = seg.get('timestamp_start', '')
            text = seg.get('text', '')
            
            if speaker != current_speaker:
                lines.append(f"\n## {speaker}\n")
                current_speaker = speaker
            
            if ts and ts != "00:00:00":
                lines.append(f"[{ts}] {text}\n")
            else:
                lines.append(f"{text}\n")
        
        return ''.join(lines)
    
    def close(self):
        """Clean up resources"""
        self.session.close()

