"""
Conversations with Tyler Site Plugin
Downloads transcripts from conversationswithtyler.com with full metadata and speaker attribution
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
class ConversationsWithTylerSite(BaseSite):
    """Conversations with Tyler podcast site plugin"""
    
    SITE_ID = "conversationswithtyler"
    SITE_NAME = "Conversations with Tyler"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript"]
    CATEGORIES = ["podcast"]
    
    BASE_URL = "https://conversationswithtyler.com"
    EPISODES_URL = "https://conversationswithtyler.com/episodes/"
    
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
        """Discover all episodes from conversationswithtyler.com/episodes/"""
        items = []
        
        if progress_callback:
            progress_callback("Fetching episodes page...")
        
        try:
            # Get the main episodes page
            response = self.session.get(self.EPISODES_URL, timeout=60)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Find all episode containers
            # The episodes page has articles with class or containing episode data
            episode_containers = soup.find_all(['article', 'div'], class_=re.compile(r'episode|post|entry'))
            
            if not episode_containers:
                # Fallback: find all links that point to episode pages
                episode_containers = soup.find_all('a', href=re.compile(r'/episodes/[^/]+/?$'))
            
            if progress_callback:
                progress_callback(f"Found {len(episode_containers)} potential episodes, parsing...")
            
            seen_urls = set()
            
            for container in episode_containers:
                try:
                    # Find the episode link
                    if container.name == 'a':
                        episode_link = container
                    else:
                        episode_link = container.find('a', href=re.compile(r'/episodes/'))
                    
                    if not episode_link:
                        continue
                    
                    href = episode_link.get('href', '')
                    if not href or href in seen_urls:
                        continue
                    
                    # Skip non-episode pages
                    if href == self.EPISODES_URL or '/episodes/' not in href:
                        continue
                    
                    seen_urls.add(href)
                    
                    # Make absolute URL
                    full_url = urljoin(self.BASE_URL, href)
                    
                    # Extract episode slug
                    slug = href.rstrip('/').split('/')[-1]
                    if not slug or slug == 'episodes':
                        continue
                    
                    # Extract metadata
                    title = None
                    episode_num = None
                    guest_name = None
                    description = None
                    
                    # Try to find episode number in container
                    episode_num_elem = container.find(string=re.compile(r'Episode\s+(\d+)', re.IGNORECASE))
                    if episode_num_elem:
                        num_match = re.search(r'Episode\s+(\d+)', episode_num_elem, re.IGNORECASE)
                        if num_match:
                            episode_num = num_match.group(1)
                    
                    # Try to get title from heading
                    heading = container.find(['h1', 'h2', 'h3', 'h4'])
                    if heading:
                        title = heading.get_text(strip=True)
                    
                    # If no title from heading, try link text
                    if not title:
                        title = episode_link.get_text(strip=True)
                    
                    # Try to get description
                    desc_elem = container.find(['p', 'div'], class_=re.compile(r'description|excerpt|summary'))
                    if desc_elem:
                        description = desc_elem.get_text(strip=True)
                    
                    # Extract guest name from title
                    if title:
                        # Remove episode number from title
                        guest_name = re.sub(r'Episode\s+\d+\s*[:\-–]?\s*', '', title, flags=re.IGNORECASE)
                        guest_name = re.sub(r'\s*\(Ep\.\s*\d+.*?\)', '', guest_name)
                        
                        # Extract just the guest name (often the first part before " on ")
                        guest_match = re.match(r'^([^:]+?)(?:\s+on\s+|\s*[:\-–]\s+)', guest_name)
                        if guest_match:
                            guest_name = guest_match.group(1).strip()
                        
                        guest_name = guest_name.strip()
                    
                    # Fallback: use slug as guest name
                    if not guest_name or len(guest_name) < 3:
                        guest_name = slug.replace('-', ' ').title()
                    
                    # Generate ID and display title
                    if episode_num:
                        item_id = f"cwt_{episode_num}_{slug}"
                        display_title = f"Episode {episode_num}: {guest_name}"
                    else:
                        item_id = f"cwt_{slug}"
                        display_title = guest_name
                    
                    # Clean up title
                    if title:
                        display_title = title
                    
                    item = ContentItem(
                        id=item_id,
                        title=display_title,
                        url=full_url,
                        asset_type="transcript",
                        category="podcast",
                        subcategory="transcripts",
                        description=description or f"Conversations with Tyler: {guest_name}"
                    )
                    
                    if item.id not in self.indexed_content:
                        self.indexed_content[item.id] = item
                        items.append(item)
                        
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"Error parsing episode: {str(e)}")
                    continue
            
            if progress_callback:
                progress_callback(f"Indexed {len(items)} episodes")
            
            return items
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error indexing: {str(e)}")
            return items
    
    def download_item(self, item: ContentItem, output_dir: str,
                      progress_callback=None) -> Tuple[bool, str]:
        """Download an episode transcript with full metadata and speaker attribution"""
        
        try:
            if progress_callback:
                progress_callback(f"Fetching episode page: {item.title}")
            
            # Fetch episode page
            response = self.session.get(item.url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Extract full metadata
            metadata = self._extract_metadata(soup, item)
            
            # Find transcript link or content
            transcript_content = self._find_transcript(soup, item.url)
            
            if not transcript_content:
                return False, "No transcript found on page"
            
            # Parse transcript with speaker attribution
            segments = self._parse_transcript_segments(transcript_content, item.id, metadata)
            
            if not segments:
                return False, "Could not parse transcript segments"
            
            # Create clean filename
            safe_guest = re.sub(r'[<>:"/\\|?*]', '', metadata.get('guest_name', 'Unknown'))
            safe_guest = re.sub(r'\s+', '_', safe_guest).strip('._')
            
            episode_num = metadata.get('episode_number', '')
            if episode_num:
                file_prefix = f"Conversations_with_Tyler_{episode_num}_{safe_guest}"
            else:
                file_prefix = f"Conversations_with_Tyler_{safe_guest}"
            
            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            
            # File paths
            txt_path = os.path.join(output_dir, f'{file_prefix}_transcript.txt')
            segments_path = os.path.join(output_dir, f'{file_prefix}_segments.json')
            metadata_path = os.path.join(output_dir, f'{file_prefix}_metadata.json')
            
            # Save plain text transcript
            plain_text = self._segments_to_text(segments, metadata)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)
            
            # Build knowledge_chipper compatible format
            episode_id = f"cwt_{episode_num}" if episode_num else item.id
            
            # Wrap each segment with context
            miner_inputs = []
            for i, seg in enumerate(segments):
                miner_input = {
                    "segment": seg,
                    "context": {
                        "episode_id": episode_id,
                        "episode_title": metadata.get('title', item.title),
                        "guest_name": metadata.get('guest_name', ''),
                        "source": "Conversations with Tyler",
                        "source_url": item.url,
                        "episode_date": metadata.get('date', ''),
                        "source_type": "crawlavator",
                        "ingestion_method": "crawlavator_import",
                        "original_source_type": "podcast_transcript"
                    },
                    "provenance": {
                        "producer_app": "crawlavator",
                        "version": "1.0.0",
                        "import_source": "conversationswithtyler.com"
                    }
                }
                
                # Add previous segments for context
                if i > 0:
                    prev_segs = []
                    for j in range(max(0, i-2), i):
                        prev_segs.append({
                            "segment_id": segments[j]["segment_id"],
                            "speaker": segments[j]["speaker"],
                            "text": segments[j]["text"][:200] + "..." if len(segments[j]["text"]) > 200 else segments[j]["text"]
                        })
                    miner_input["context"]["previous_segments"] = prev_segs
                
                miner_inputs.append(miner_input)
            
            # Save segments JSON
            with open(segments_path, 'w', encoding='utf-8') as f:
                json.dump(miner_inputs, f, indent=2, ensure_ascii=False)
            
            # Save metadata
            metadata['id'] = item.id
            metadata['episode_id'] = episode_id
            metadata['url'] = item.url
            metadata['segment_count'] = len(segments)
            metadata['source'] = 'Conversations with Tyler'
            metadata['source_url'] = 'conversationswithtyler.com'
            metadata['source_type'] = 'crawlavator'
            metadata['ingestion_method'] = 'crawlavator_import'
            metadata['original_source_type'] = 'podcast_transcript'
            metadata['provenance'] = {
                'producer_app': 'crawlavator',
                'version': '1.0.0',
                'import_source': 'conversationswithtyler.com'
            }
            
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            return True, f"Saved {len(segments)} segments"
            
        except Exception as e:
            return False, f"Download error: {str(e)}"
    
    def _extract_metadata(self, soup: BeautifulSoup, item: ContentItem) -> Dict[str, Any]:
        """Extract full metadata from episode page"""
        metadata = {}
        
        # Extract title
        title_elem = soup.find('h1')
        if title_elem:
            metadata['title'] = title_elem.get_text(strip=True)
        else:
            metadata['title'] = item.title
        
        # Extract episode number
        episode_num_match = re.search(r'Episode\s+(\d+)', metadata['title'], re.IGNORECASE)
        if not episode_num_match:
            episode_num_match = re.search(r'\(Ep\.\s*(\d+)', metadata['title'], re.IGNORECASE)
        if episode_num_match:
            metadata['episode_number'] = episode_num_match.group(1)
        
        # Extract guest name
        guest_name = metadata['title']
        guest_name = re.sub(r'Episode\s+\d+\s*[:\-–]?\s*', '', guest_name, flags=re.IGNORECASE)
        guest_name = re.sub(r'\s*\(Ep\.\s*\d+.*?\)', '', guest_name)
        guest_match = re.match(r'^([^:]+?)(?:\s+on\s+|\s*[:\-–]\s+)', guest_name)
        if guest_match:
            metadata['guest_name'] = guest_match.group(1).strip()
        else:
            metadata['guest_name'] = guest_name.strip()
        
        # Extract date
        date_elem = soup.find('time')
        if date_elem:
            metadata['date'] = date_elem.get('datetime', '') or date_elem.get_text(strip=True)
        
        # Extract description
        desc_elem = soup.find('meta', {'name': 'description'})
        if desc_elem:
            metadata['description'] = desc_elem.get('content', '')
        
        # Extract topics/tags
        topics = []
        for tag_elem in soup.find_all(['a', 'span'], class_=re.compile(r'tag|topic|category')):
            topic = tag_elem.get_text(strip=True)
            if topic and len(topic) < 50:
                topics.append(topic)
        if topics:
            metadata['topics'] = topics
        
        return metadata
    
    def _find_transcript(self, soup: BeautifulSoup, page_url: str) -> Optional[BeautifulSoup]:
        """Find the transcript content on the page"""
        
        # The transcript is embedded in the page itself
        # Look for the main content area - it's in the body
        # The transcript starts after the intro paragraphs
        
        # Get the body or main container
        transcript_content = soup.find('body')
        
        if not transcript_content:
            transcript_content = soup
        
        return transcript_content
    
    def _parse_transcript_segments(self, content: BeautifulSoup, episode_id: str, 
                                   metadata: Dict[str, Any]) -> List[Dict]:
        """Parse transcript into segments with speaker attribution"""
        segments = []
        
        if not content:
            return segments
        
        segment_idx = 0
        current_speaker = "Unknown"
        
        # Get all paragraphs - the transcript is in <p> tags
        paragraphs = content.find_all('p')
        
        for para in paragraphs:
            try:
                text = para.get_text(strip=True)
                
                # Skip short paragraphs (navigation, etc)
                if len(text) < 50:
                    continue
                
                # Check for speaker patterns - Conversations with Tyler uses "SPEAKER NAME:" format
                # Pattern: "TYLER COWEN:" or "GOPNIK:" or "ALISON GOPNIK:"
                speaker_match = re.match(r'^([A-Z][A-Z\s]+):\s*(.+)', text, re.DOTALL)
                
                if speaker_match:
                    # Found a speaker label
                    speaker_name = speaker_match.group(1).strip()
                    segment_text = speaker_match.group(2).strip()
                    
                    # Normalize speaker names
                    if 'COWEN' in speaker_name or 'TYLER' in speaker_name:
                        current_speaker = "Tyler Cowen"
                    else:
                        # Use the guest name from metadata if available
                        guest = metadata.get('guest_name', '')
                        if guest:
                            current_speaker = guest
                        else:
                            # Clean up the speaker name
                            current_speaker = speaker_name.title()
                    
                    # Create segment
                    if len(segment_text) > 20:
                        segment = {
                            'segment_id': f"{episode_id}_seg_{segment_idx:04d}",
                            'speaker': current_speaker,
                            'text': segment_text
                        }
                        segments.append(segment)
                        segment_idx += 1
                else:
                    # No speaker label - this might be a continuation or intro text
                    # Skip intro/description paragraphs (they usually don't have speaker labels)
                    # Only include if we've already started collecting segments
                    if segment_idx > 0 and len(text) > 50:
                        # Continuation of previous speaker
                        segment = {
                            'segment_id': f"{episode_id}_seg_{segment_idx:04d}",
                            'speaker': current_speaker,
                            'text': text
                        }
                        segments.append(segment)
                        segment_idx += 1
                
            except Exception:
                continue
        
        return segments
    
    def _parse_transcript_fallback(self, content, episode_id: str) -> List[Dict]:
        """Fallback parser when standard parsing fails"""
        segments = []
        
        # Get all text content
        text = content.get_text(separator='\n', strip=True)
        
        # Split by speaker patterns
        speaker_pattern = re.compile(r'\n([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:\s*', re.MULTILINE)
        
        parts = speaker_pattern.split(text)
        
        current_speaker = "Unknown"
        segment_idx = 0
        
        for i, part in enumerate(parts):
            if not part.strip():
                continue
            
            # Check if this is a speaker name
            if i % 2 == 1:  # Odd indices are speaker names from split
                current_speaker = part.strip()
                continue
            
            # This is content
            # Split long content into manageable chunks
            paragraphs = part.split('\n\n')
            
            for para in paragraphs:
                para = para.strip()
                if len(para) < 50:
                    continue
                
                segment = {
                    'segment_id': f"{episode_id}_seg_{segment_idx:04d}",
                    'speaker': current_speaker,
                    'text': para[:2000]  # Limit segment length
                }
                
                segments.append(segment)
                segment_idx += 1
        
        return segments
    
    def _segments_to_text(self, segments: List[Dict], metadata: Dict[str, Any]) -> str:
        """Convert segments to plain text transcript"""
        title = metadata.get('title', 'Conversations with Tyler')
        guest = metadata.get('guest_name', '')
        date = metadata.get('date', '')
        
        lines = [f"# {title}\n"]
        
        if guest:
            lines.append(f"Guest: {guest}\n")
        if date:
            lines.append(f"Date: {date}\n")
        
        lines.append("\n---\n\n")
        
        current_speaker = None
        
        for seg in segments:
            speaker = seg.get('speaker', 'Unknown')
            text = seg.get('text', '')
            
            if speaker != current_speaker:
                lines.append(f"\n## {speaker}\n\n")
                current_speaker = speaker
            
            lines.append(f"{text}\n\n")
        
        return ''.join(lines)
    
    def close(self):
        """Clean up resources"""
        self.session.close()

