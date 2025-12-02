"""
Video Extractor
Downloads videos from eurodollar.university using HLS stream extraction
"""

import os
import re
import subprocess
import shutil
import threading
from typing import Optional, Tuple, Callable
from playwright.sync_api import Page

from edu_auth import EDUAuth


class VideoExtractor:
    """Extracts and downloads videos from Squarespace-hosted pages"""
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
    
    def _find_ffmpeg(self) -> Optional[str]:
        """Find ffmpeg binary"""
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path
        
        common_paths = [
            '/opt/homebrew/bin/ffmpeg',
            '/usr/local/bin/ffmpeg',
            '/usr/bin/ffmpeg',
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _find_ffprobe(self) -> Optional[str]:
        """Find ffprobe binary"""
        ffprobe_path = shutil.which('ffprobe')
        if ffprobe_path:
            return ffprobe_path
        
        common_paths = [
            '/opt/homebrew/bin/ffprobe',
            '/usr/local/bin/ffprobe',
            '/usr/bin/ffprobe',
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def extract_video_url(self, video_page_url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Visit a video page and extract the HLS/direct video URL
        Returns (video_url, error_message)
        """
        page = self.auth.get_page()
        video_urls = []
        
        try:
            # Set up request interception to capture video URLs
            def handle_response(response):
                url = response.url
                content_type = response.headers.get('content-type', '')
                
                if url.startswith('blob:'):
                    return
                
                # Look for video files, HLS manifests
                video_indicators = ['.mp4', '.webm', '.m3u8', '/video/', 'sqspcdn']
                if any(ind in url.lower() for ind in video_indicators):
                    video_urls.append(url)
                elif 'video' in content_type.lower():
                    video_urls.append(url)
            
            page.on('response', handle_response)
            
            # Navigate to the video page
            page.goto(video_page_url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            
            # Try to trigger video playback
            try:
                play_selectors = [
                    'button[aria-label*="play" i]',
                    '.play-button',
                    '[class*="play"]',
                    'video',
                ]
                for selector in play_selectors:
                    try:
                        element = page.query_selector(selector)
                        if element:
                            element.click()
                            page.wait_for_timeout(3000)
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            
            page.wait_for_timeout(2000)
            
            # Also search page content for video URLs
            try:
                page_content = page.content()
                url_patterns = [
                    r'https://[^"\s]+\.m3u8[^"\s]*',
                    r'https://[^"\s]+\.mp4[^"\s]*',
                    r'https://[^"\s]+sqspcdn[^"\s]+video[^"\s]*',
                    r'"videoUrl"\s*:\s*"([^"]+)"',
                    r'"src"\s*:\s*"(https://[^"]+\.(mp4|m3u8)[^"]*)"',
                ]
                
                for pattern in url_patterns:
                    matches = re.findall(pattern, page_content)
                    for match in matches:
                        url = match if isinstance(match, str) else match[0]
                        if url.startswith('http') and 'blob:' not in url:
                            video_urls.append(url)
            except Exception:
                pass
            
            # Filter and prioritize
            seen = set()
            unique_urls = []
            for u in video_urls:
                if u not in seen and not u.startswith('blob:'):
                    seen.add(u)
                    unique_urls.append(u)
            
            # Prefer m3u8 (HLS), then MP4
            m3u8_urls = [u for u in unique_urls if '.m3u8' in u.lower()]
            mp4_urls = [u for u in unique_urls if '.mp4' in u.lower()]
            
            if m3u8_urls:
                # Prefer index.m3u8 over segment manifests
                index_m3u8 = [u for u in m3u8_urls if 'index' in u.lower() or 'master' in u.lower()]
                return (index_m3u8[0] if index_m3u8 else m3u8_urls[0]), None
            elif mp4_urls:
                return mp4_urls[0], None
            elif unique_urls:
                return unique_urls[0], None
            else:
                return None, "Could not find video URL"
                
        except Exception as e:
            return None, str(e)
        finally:
            page.close()
    
    def get_video_duration(self, path_or_url: str, is_url: bool = False) -> Optional[float]:
        """Get video duration in seconds using ffprobe"""
        try:
            ffprobe = self._find_ffprobe()
            if not ffprobe:
                return None
            
            cmd = [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
                   '-of', 'default=noprint_wrappers=1:nokey=1']
            
            if is_url:
                cookie_str = self.auth.get_cookie_string()
                if cookie_str:
                    cmd.extend(['-headers', f'Cookie: {cookie_str}\r\n'])
            
            cmd.append(path_or_url)
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return None
    
    def is_video_complete(self, existing_path: str, source_url: str) -> Tuple[bool, str]:
        """Check if existing video is complete"""
        if not os.path.exists(existing_path):
            return False, "File does not exist"
        
        existing_size = os.path.getsize(existing_path)
        if existing_size < 1_000_000:  # Less than 1MB
            return False, "File too small"
        
        existing_duration = self.get_video_duration(existing_path)
        if existing_duration is None:
            return False, "Could not read file duration"
        
        source_duration = self.get_video_duration(source_url, is_url=True)
        if source_duration is None:
            # Can't verify, assume complete if > 1 min
            if existing_duration > 60:
                return True, f"Source unavailable, file is {existing_duration:.0f}s"
            return False, "Could not verify against source"
        
        duration_diff = abs(source_duration - existing_duration)
        if duration_diff <= 5 or existing_duration >= (source_duration * 0.98):
            return True, f"Complete: {existing_duration:.0f}s / {source_duration:.0f}s"
        
        return False, f"Incomplete: {existing_duration:.0f}s vs {source_duration:.0f}s expected"
    
    def download_video(self, video_page_url: str, output_path: str,
                       progress_callback: Optional[Callable[[int], None]] = None,
                       skip_if_exists: bool = True) -> Tuple[bool, str]:
        """
        Download video from a page URL to the specified path.
        Returns (success, message)
        """
        # Extract video URL
        video_url, error = self.extract_video_url(video_page_url)
        
        if error:
            return False, error
        
        if not video_url:
            return False, "No video URL found"
        
        # Check if already complete
        if skip_if_exists and os.path.exists(output_path):
            is_complete, msg = self.is_video_complete(output_path, video_url)
            if is_complete:
                return True, f"Already complete: {msg}"
        
        # Download based on URL type
        if '.m3u8' in video_url.lower():
            return self._download_hls(video_url, output_path, progress_callback)
        else:
            return self._download_direct(video_url, output_path, progress_callback)
    
    def _download_hls(self, m3u8_url: str, output_path: str,
                      progress_callback: Optional[Callable[[int], None]] = None) -> Tuple[bool, str]:
        """Download HLS stream using ffmpeg"""
        try:
            ffmpeg = self._find_ffmpeg()
            if not ffmpeg:
                return False, "ffmpeg not found. Please install: brew install ffmpeg"
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            temp_path = output_path + '.tmp'
            
            # Get cookies for authentication
            cookie_str = self.auth.get_cookie_string()
            
            cmd = [
                ffmpeg,
                '-y',
                '-headers', f'Cookie: {cookie_str}\r\nReferer: https://www.eurodollar.university/\r\nUser-Agent: Mozilla/5.0\r\n',
                '-i', m3u8_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                '-f', 'mp4',
                temp_path
            ]
            
            # Run with progress monitoring
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            stop_monitoring = threading.Event()
            
            def monitor_progress():
                last_size = 0
                while not stop_monitoring.is_set():
                    if os.path.exists(temp_path):
                        size = os.path.getsize(temp_path)
                        if size != last_size and progress_callback:
                            progress_callback(size)
                            last_size = size
                    stop_monitoring.wait(1)
            
            if progress_callback:
                monitor_thread = threading.Thread(target=monitor_progress)
                monitor_thread.start()
            
            try:
                stdout, stderr = process.communicate(timeout=1800)  # 30 min timeout
            finally:
                stop_monitoring.set()
                if progress_callback:
                    monitor_thread.join(timeout=2)
            
            if process.returncode != 0:
                # Try without bsf filter
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                
                cmd_simple = [
                    ffmpeg, '-y',
                    '-headers', f'Cookie: {cookie_str}\r\nReferer: https://www.eurodollar.university/\r\n',
                    '-i', m3u8_url,
                    '-c', 'copy',
                    '-f', 'mp4',
                    temp_path
                ]
                result = subprocess.run(cmd_simple, capture_output=True, text=True, timeout=1800)
                
                if result.returncode != 0:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    error_msg = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr
                    return False, f"ffmpeg failed: {error_msg}"
            
            # Move to final path
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_path, output_path)
                size_mb = os.path.getsize(output_path) // 1_000_000
                return True, f"Video saved ({size_mb}MB)"
            else:
                return False, "No output file created"
                
        except subprocess.TimeoutExpired:
            return False, "Download timed out (30 min limit)"
        except Exception as e:
            return False, f"HLS download error: {str(e)}"
    
    def _download_direct(self, video_url: str, output_path: str,
                         progress_callback: Optional[Callable[[int], None]] = None) -> Tuple[bool, str]:
        """Download video directly via HTTP"""
        import requests
        
        temp_path = output_path + '.tmp'
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            cookies = self.auth.get_cookies()
            
            response = requests.get(
                video_url,
                cookies=cookies,
                stream=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                    'Referer': 'https://www.eurodollar.university/'
                },
                timeout=30
            )
            
            if response.status_code != 200:
                return False, f"Download failed: HTTP {response.status_code}"
            
            downloaded = 0
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded)
            
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_path, output_path)
                size_mb = os.path.getsize(output_path) // 1_000_000
                return True, f"Video saved ({size_mb}MB)"
            
            return False, "No file created"
            
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False, f"Download error: {str(e)}"

