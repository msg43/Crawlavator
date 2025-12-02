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
            segments = self._parse_transcript_segments(soup, item.id, title)
            
            # Save plain text transcript
            plain_text = self._segments_to_text(segments, title)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)
            
            # Save segments JSON (knowledge_chipper format)
            with open(segments_path, 'w', encoding='utf-8') as f:
                json.dump(segments, f, indent=2, ensure_ascii=False)
            
            # Save metadata
            metadata = {
                'id': item.id,
                'title': title,
                'url': item.url,
                'episode_number': episode_num,
                'segment_count': len(segments),
                'source': 'lexfridman.com'
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
        
        # Look for timestamped segments
        # Lex Fridman format: Speaker name, timestamp link, then text
        # Example: <span>Lex Fridman</span> <a href="...">(00:00:45)</a> text...
        
        segment_idx = 0
        current_speaker = "Unknown"
        
        # Find all elements that might contain segments
        # The transcript uses divs/paragraphs with speaker + timestamp + text
        
        # First try to find timestamp links
        timestamp_links = content.find_all('a', href=re.compile(r'[?&]t=\d+'))
        
        for ts_link in timestamp_links:
            try:
                # Get timestamp
                ts_text = ts_link.get_text(strip=True)
                ts_match = re.search(r'\((\d{2}:\d{2}:\d{2})\)', ts_text)
                if not ts_match:
                    continue
                
                timestamp = ts_match.group(1)
                
                # Get speaker (usually in preceding element)
                parent = ts_link.parent
                speaker_elem = parent.find_previous(['span', 'strong', 'b'])
                if speaker_elem:
                    speaker_text = speaker_elem.get_text(strip=True)
                    # Check if it looks like a speaker name
                    if speaker_text and len(speaker_text) < 50 and not speaker_text.startswith('('):
                        current_speaker = speaker_text
                
                # Get text (everything after timestamp until next timestamp)
                text_parts = []
                for sibling in ts_link.next_siblings:
                    if hasattr(sibling, 'name'):
                        # Check if this is another timestamp
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
                
                # Calculate end timestamp (use next segment's start or add 60s)
                # We'll fix this in a second pass
                end_timestamp = timestamp
                
                segment = {
                    'segment_id': f"{episode_id}_seg_{segment_idx:04d}",
                    'speaker': current_speaker,
                    'timestamp_start': timestamp,
                    'timestamp_end': end_timestamp,
                    'text': segment_text
                }
                
                segments.append(segment)
                segment_idx += 1
                
            except Exception:
                continue
        
        # Second pass: fix end timestamps
        for i in range(len(segments) - 1):
            segments[i]['timestamp_end'] = segments[i + 1]['timestamp_start']
        
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

