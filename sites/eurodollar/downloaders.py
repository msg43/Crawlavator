"""
Eurodollar University Downloaders
Video, Article, and PDF/Audio downloaders
"""

import os
import re
import subprocess
import shutil
import threading
import requests
from typing import Tuple, Optional, Callable
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from .auth import EDUAuth


class VideoExtractor:
    """Extracts and downloads videos from Squarespace-hosted pages"""
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
    
    def _find_ffmpeg(self) -> Optional[str]:
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path
        for path in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']:
            if os.path.exists(path):
                return path
        return None
    
    def _find_ffprobe(self) -> Optional[str]:
        ffprobe_path = shutil.which('ffprobe')
        if ffprobe_path:
            return ffprobe_path
        for path in ['/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe', '/usr/bin/ffprobe']:
            if os.path.exists(path):
                return path
        return None
    
    def extract_video_url(self, video_page_url: str) -> Tuple[Optional[str], Optional[str]]:
        page = self.auth.get_page()
        video_urls = []
        
        try:
            def handle_response(response):
                url = response.url
                content_type = response.headers.get('content-type', '')
                if url.startswith('blob:'):
                    return
                video_indicators = ['.mp4', '.webm', '.m3u8', '/video/', 'sqspcdn']
                if any(ind in url.lower() for ind in video_indicators):
                    video_urls.append(url)
                elif 'video' in content_type.lower():
                    video_urls.append(url)
            
            page.on('response', handle_response)
            page.goto(video_page_url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            
            # Try to trigger playback
            for selector in ['button[aria-label*="play" i]', '.play-button', '[class*="play"]', 'video']:
                try:
                    element = page.query_selector(selector)
                    if element:
                        element.click()
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue
            
            page.wait_for_timeout(2000)
            
            # Search page content
            try:
                page_content = page.content()
                url_patterns = [
                    r'https://[^"\s]+\.m3u8[^"\s]*',
                    r'https://[^"\s]+\.mp4[^"\s]*',
                    r'https://[^"\s]+sqspcdn[^"\s]+video[^"\s]*',
                ]
                for pattern in url_patterns:
                    matches = re.findall(pattern, page_content)
                    for match in matches:
                        url = match if isinstance(match, str) else match[0]
                        if url.startswith('http') and 'blob:' not in url:
                            video_urls.append(url)
            except Exception:
                pass
            
            # Dedupe and prioritize
            seen = set()
            unique_urls = []
            for u in video_urls:
                if u not in seen and not u.startswith('blob:'):
                    seen.add(u)
                    unique_urls.append(u)
            
            m3u8_urls = [u for u in unique_urls if '.m3u8' in u.lower()]
            mp4_urls = [u for u in unique_urls if '.mp4' in u.lower()]
            
            if m3u8_urls:
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
        if not os.path.exists(existing_path):
            return False, "File does not exist"
        
        existing_size = os.path.getsize(existing_path)
        if existing_size < 1_000_000:
            return False, "File too small"
        
        existing_duration = self.get_video_duration(existing_path)
        if existing_duration is None:
            return False, "Could not read file duration"
        
        source_duration = self.get_video_duration(source_url, is_url=True)
        if source_duration is None:
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
        video_url, error = self.extract_video_url(video_page_url)
        
        if error:
            return False, error
        if not video_url:
            return False, "No video URL found"
        
        if skip_if_exists and os.path.exists(output_path):
            is_complete, msg = self.is_video_complete(output_path, video_url)
            if is_complete:
                return True, f"Already complete: {msg}"
        
        if '.m3u8' in video_url.lower():
            return self._download_hls(video_url, output_path, progress_callback)
        else:
            return self._download_direct(video_url, output_path, progress_callback)
    
    def _download_hls(self, m3u8_url: str, output_path: str,
                      progress_callback: Optional[Callable[[int], None]] = None) -> Tuple[bool, str]:
        try:
            ffmpeg = self._find_ffmpeg()
            if not ffmpeg:
                return False, "ffmpeg not found. Please install: brew install ffmpeg"
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            temp_path = output_path + '.tmp'
            cookie_str = self.auth.get_cookie_string()
            
            cmd = [
                ffmpeg, '-y',
                '-headers', f'Cookie: {cookie_str}\r\nReferer: https://www.eurodollar.university/\r\nUser-Agent: Mozilla/5.0\r\n',
                '-i', m3u8_url,
                '-c', 'copy', '-bsf:a', 'aac_adtstoasc', '-f', 'mp4', temp_path
            ]
            
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
                stdout, stderr = process.communicate(timeout=1800)
            finally:
                stop_monitoring.set()
                if progress_callback:
                    monitor_thread.join(timeout=2)
            
            if process.returncode != 0:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                cmd_simple = [
                    ffmpeg, '-y',
                    '-headers', f'Cookie: {cookie_str}\r\nReferer: https://www.eurodollar.university/\r\n',
                    '-i', m3u8_url, '-c', 'copy', '-f', 'mp4', temp_path
                ]
                result = subprocess.run(cmd_simple, capture_output=True, text=True, timeout=1800)
                if result.returncode != 0:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    error_msg = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr
                    return False, f"ffmpeg failed: {error_msg}"
            
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
        temp_path = output_path + '.tmp'
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cookies = self.auth.get_cookies()
            
            response = requests.get(
                video_url, cookies=cookies, stream=True,
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.eurodollar.university/'},
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


class ArticleDownloader:
    """Downloads HTML articles with embedded images"""
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
    
    def _get_authenticated_session(self) -> requests.Session:
        """Create a requests session with authenticated cookies"""
        cookies = self.auth.get_cookies()
        
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(
                cookie['name'],
                cookie['value'],
                domain=cookie.get('domain', ''),
                path=cookie.get('path', '/')
            )
        
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        return session
    
    def _download_article_fast(self, article_url: str, html_path: str, images_dir: str) -> bool:
        """Fast article download using HTTP requests"""
        session = self._get_authenticated_session()
        
        # Fetch page
        response = session.get(article_url, timeout=15)
        if response.status_code in [403, 404]:
            return False
        response.raise_for_status()
        
        # Parse and extract article
        soup = BeautifulSoup(response.content, 'lxml')
        article = soup.select_one('article, .blog-item, .post-content, main article')
        if not article:
            article = soup.select_one('main, .content')
        if not article or len(article.get_text(strip=True)) < 200:
            return False
        
        # Download images
        os.makedirs(images_dir, exist_ok=True)
        images = article.find_all('img')
        
        for img in images:
            src = img.get('src') or img.get('data-src')
            if not src or not src.startswith('http'):
                continue
            
            try:
                img_response = session.get(src, timeout=10)
                if img_response.status_code == 200:
                    filename = os.path.basename(urlparse(src).path) or 'image.jpg'
                    img_path = os.path.join(images_dir, filename)
                    with open(img_path, 'wb') as f:
                        f.write(img_response.content)
                    # Update src to local path
                    img['src'] = f'images/{filename}'
            except:
                pass
        
        # Save HTML
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(str(article))
        
        return True
    
    def _download_transcript_fast(self, page_url: str, transcript_title: str) -> Optional[str]:
        """Fast transcript download using HTTP requests instead of Playwright"""
        session = self._get_authenticated_session()
        
        # Make fast HTTP request
        response = session.get(page_url, timeout=15)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'lxml')
        
        # Try to find transcript content (same selectors as Playwright version)
        content = None
        selectors = [
            '.accordion-content',
            '[class*="accordion"] [class*="content"]',
            '.sqs-block-content',
            'article',
            'main',
            '.content'
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            for elem in elements:
                text = elem.get_text(separator='\n', strip=True)
                if len(text) > 500:  # Reasonable transcript length
                    content = text
                    break
            if content:
                break
        
        return content
    
    def download_article(self, article_url: str, output_dir: str,
                         skip_if_exists: bool = True) -> Tuple[bool, str]:
        os.makedirs(output_dir, exist_ok=True)
        
        html_path = os.path.join(output_dir, 'article.html')
        images_dir = os.path.join(output_dir, 'images')
        
        if skip_if_exists and os.path.exists(html_path):
            if os.path.getsize(html_path) > 1000:
                return True, "Article already downloaded"
        
        # OPTIMIZATION: Try fast HTTP request first for simple articles
        try:
            success = self._download_article_fast(article_url, html_path, images_dir)
            if success:
                return True, html_path
        except Exception:
            pass  # Fallback to Playwright
        
        # Fallback to Playwright for complex pages
        page = self.auth.get_page()
        
        try:
            response = page.goto(article_url, wait_until='networkidle', timeout=30000)
            
            if response and response.status == 403:
                page.close()
                return False, "Access denied (403)"
            if response and response.status == 404:
                page.close()
                return False, "Article not found (404)"
            if '/account/login' in page.url.lower():
                page.close()
                return False, "Authentication required"
            
            page.wait_for_timeout(2000)
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'lxml')
            
            article = soup.select_one('article, .blog-item, .post-content, main article')
            if not article:
                article = soup.select_one('main, .content')
            if not article:
                article = soup.find('body')
            if not article:
                page.close()
                return False, "Could not find article content"
            
            # Download images
            os.makedirs(images_dir, exist_ok=True)
            images = article.find_all('img')
            image_count = 0
            cookies = self.auth.get_cookies()
            
            for img in images:
                src = img.get('src') or img.get('data-src')
                if not src:
                    continue
                if not src.startswith('http'):
                    src = urljoin(article_url, src)
                
                try:
                    img_response = requests.get(
                        src, cookies=cookies,
                        headers={'User-Agent': 'Mozilla/5.0', 'Referer': article_url},
                        timeout=30
                    )
                    if img_response.status_code == 200:
                        ext = self._get_image_extension(src, img_response.headers.get('content-type', ''))
                        img_filename = f"image_{image_count:03d}{ext}"
                        img_path = os.path.join(images_dir, img_filename)
                        with open(img_path, 'wb') as f:
                            f.write(img_response.content)
                        img['src'] = f"images/{img_filename}"
                        if img.get('data-src'):
                            del img['data-src']
                        image_count += 1
                except Exception:
                    pass
            
            # Clean up HTML
            for tag in article.find_all(['script', 'noscript', 'iframe']):
                tag.decompose()
            for tag in article.find_all(class_=re.compile(r'sqs-(block-button|cookie|newsletter)')):
                tag.decompose()
            
            title = soup.title.string if soup.title else "Article"
            standalone_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem; line-height: 1.6; color: #333; }}
        img {{ max-width: 100%; height: auto; }}
        h1, h2, h3 {{ margin-top: 1.5em; }}
        p {{ margin: 1em 0; }}
    </style>
</head>
<body>
    <article>{article.decode_contents()}</article>
    <footer><p><small>Downloaded from: <a href="{article_url}">{article_url}</a></small></p></footer>
</body>
</html>"""
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(standalone_html)
            
            page.close()
            return True, f"Article saved with {image_count} images"
            
        except Exception as e:
            page.close()
            return False, f"Download error: {str(e)}"
    
    def _get_image_extension(self, url: str, content_type: str) -> str:
        path = urlparse(url).path.lower()
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']:
            if path.endswith(ext):
                return ext
        if 'jpeg' in content_type or 'jpg' in content_type:
            return '.jpg'
        elif 'png' in content_type:
            return '.png'
        elif 'gif' in content_type:
            return '.gif'
        elif 'webp' in content_type:
            return '.webp'
        return '.jpg'
    
    def download_transcript(self, page_url: str, transcript_title: str,
                            output_dir: str, skip_if_exists: bool = True) -> Tuple[bool, str]:
        os.makedirs(output_dir, exist_ok=True)
        txt_path = os.path.join(output_dir, f"{self._safe_filename(transcript_title)}.txt")
        
        if skip_if_exists and os.path.exists(txt_path):
            if os.path.getsize(txt_path) > 100:
                return True, "Transcript already downloaded"
        
        # OPTIMIZATION: Try fast HTTP request first, fallback to Playwright if needed
        try:
            content = self._download_transcript_fast(page_url, transcript_title)
            if content and len(content) > 100:
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {transcript_title}\n\n{content}")
                return True, txt_path
        except Exception as e:
            # Fast method failed, fallback to Playwright
            pass
        
        # Fallback to Playwright for complex pages (accordions, JavaScript content)
        page = self.auth.get_page()
        
        try:
            response = page.goto(page_url, wait_until='networkidle', timeout=30000)
            if response and response.status in [403, 404]:
                page.close()
                return False, f"Access error: HTTP {response.status}"
            
            page.wait_for_timeout(2000)
            
            # Click accordion
            try:
                accordion_button = page.locator(f'button:has-text("{transcript_title}")').first
                if accordion_button.count() > 0:
                    accordion_button.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass
            
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            content = None
            selectors = ['.accordion-content', '[class*="accordion"] [class*="content"]', '.sqs-block-content']
            for selector in selectors:
                elements = soup.select(selector)
                for elem in elements:
                    text = elem.get_text(strip=True)
                    if len(text) > 500:
                        content = text
                        break
                if content:
                    break
            
            if not content:
                main = soup.select_one('main, article, .content')
                if main:
                    content = main.get_text(separator='\n', strip=True)
            
            if not content or len(content) < 100:
                page.close()
                return False, "Could not extract transcript content"
            
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"# {transcript_title}\n\n")
                f.write(content)
            
            page.close()
            return True, f"Transcript saved ({len(content)} chars)"
            
        except Exception as e:
            page.close()
            return False, f"Download error: {str(e)}"
    
    def _safe_filename(self, name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        if len(safe) > 100:
            safe = safe[:100]
        return safe or 'untitled'


class PDFDownloader:
    """Downloads PDFs, audio files, and other direct downloads"""
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
    
    def download_file(self, url: str, output_path: str,
                      progress_callback: Optional[Callable[[int], None]] = None,
                      skip_if_exists: bool = True) -> Tuple[bool, str]:
        if skip_if_exists and os.path.exists(output_path):
            if os.path.getsize(output_path) > 1000:
                return True, "File already downloaded"
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_path = output_path + '.tmp'
        
        try:
            cookies = self.auth.get_cookies()
            response = requests.get(
                url, cookies=cookies, stream=True,
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.eurodollar.university/'},
                timeout=60
            )
            
            if response.status_code == 403:
                return False, "Access denied (403)"
            if response.status_code == 404:
                return False, "File not found (404)"
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
                size_kb = os.path.getsize(output_path) // 1024
                return True, f"Downloaded ({size_kb}KB)"
            
            return False, "No file created"
            
        except requests.exceptions.Timeout:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False, "Download timed out"
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False, f"Download error: {str(e)}"
    
    def download_daily_briefing(self, page_url: str, briefing_title: str,
                                 output_dir: str, skip_if_exists: bool = True) -> Tuple[bool, str]:
        os.makedirs(output_dir, exist_ok=True)
        safe_title = self._safe_filename(briefing_title)
        pdf_path = os.path.join(output_dir, f"{safe_title}.pdf")
        
        if skip_if_exists and os.path.exists(pdf_path):
            if os.path.getsize(pdf_path) > 10000:
                return True, "PDF already downloaded"
        
        page = self.auth.get_page()
        
        try:
            response = page.goto(page_url, wait_until='networkidle', timeout=30000)
            if response and response.status in [403, 404]:
                page.close()
                return False, f"Access error: HTTP {response.status}"
            
            page.wait_for_timeout(2000)
            
            try:
                accordion_button = page.locator(f'button:has-text("{briefing_title}")').first
                if accordion_button.count() > 0:
                    accordion_button.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
            
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            pdf_link = None
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower():
                    pdf_link = href
                    break
            
            if not pdf_link:
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if 'download' in href.lower() or 'download' in link.get_text().lower():
                        if 'pdf' in link.get_text().lower() or 'briefing' in link.get_text().lower():
                            pdf_link = href
                            break
            
            page.close()
            
            if not pdf_link:
                return False, "Could not find PDF link"
            
            if not pdf_link.startswith('http'):
                pdf_link = urljoin(page_url, pdf_link)
            
            return self.download_file(pdf_link, pdf_path, skip_if_exists=False)
            
        except Exception as e:
            page.close()
            return False, f"Download error: {str(e)}"
    
    def _safe_filename(self, name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        if len(safe) > 100:
            safe = safe[:100]
        return safe or 'untitled'

