"""
PDF and Audio Downloader
Downloads PDFs and audio files from eurodollar.university
"""

import os
import re
import requests
from typing import Tuple, Optional, Callable
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import Page

from edu_auth import EDUAuth


class PDFDownloader:
    """Downloads PDFs, audio files, and other direct downloads"""
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
    
    def download_file(self, url: str, output_path: str,
                      progress_callback: Optional[Callable[[int], None]] = None,
                      skip_if_exists: bool = True) -> Tuple[bool, str]:
        """
        Download a file directly from URL.
        Returns (success, message)
        """
        # Check if exists
        if skip_if_exists and os.path.exists(output_path):
            if os.path.getsize(output_path) > 1000:  # More than 1KB
                return True, "File already downloaded"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        temp_path = output_path + '.tmp'
        
        try:
            cookies = self.auth.get_cookies()
            
            response = requests.get(
                url,
                cookies=cookies,
                stream=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                    'Referer': 'https://www.eurodollar.university/'
                },
                timeout=60
            )
            
            if response.status_code == 403:
                return False, "Access denied (403)"
            
            if response.status_code == 404:
                return False, "File not found (404)"
            
            if response.status_code != 200:
                return False, f"Download failed: HTTP {response.status_code}"
            
            # Get total size if available
            total_size = int(response.headers.get('content-length', 0))
            
            downloaded = 0
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded)
            
            # Verify download
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
                                 output_dir: str, 
                                 skip_if_exists: bool = True) -> Tuple[bool, str]:
        """
        Download a Daily Briefing PDF by expanding accordion.
        Returns (success, message)
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate safe filename
        safe_title = self._safe_filename(briefing_title)
        pdf_path = os.path.join(output_dir, f"{safe_title}.pdf")
        
        if skip_if_exists and os.path.exists(pdf_path):
            if os.path.getsize(pdf_path) > 10000:  # More than 10KB
                return True, "PDF already downloaded"
        
        page = self.auth.get_page()
        
        try:
            response = page.goto(page_url, wait_until='networkidle', timeout=30000)
            
            if response and response.status in [403, 404]:
                page.close()
                return False, f"Access error: HTTP {response.status}"
            
            page.wait_for_timeout(2000)
            
            # Find and click the accordion for this briefing
            try:
                accordion_button = page.locator(f'button:has-text("{briefing_title}")').first
                if accordion_button.count() > 0:
                    accordion_button.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
            
            # Look for PDF link in expanded content
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            pdf_link = None
            
            # Search for PDF links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower():
                    pdf_link = href
                    break
            
            # Also check for download buttons/links
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
            
            # Make absolute URL
            if not pdf_link.startswith('http'):
                pdf_link = urljoin(page_url, pdf_link)
            
            # Download the PDF
            return self.download_file(pdf_link, pdf_path, skip_if_exists=False)
            
        except Exception as e:
            page.close()
            return False, f"Download error: {str(e)}"
    
    def find_and_download_pdfs(self, page_url: str, output_dir: str,
                                skip_if_exists: bool = True) -> Tuple[int, int, list]:
        """
        Find and download all PDFs from a page.
        Returns (success_count, fail_count, errors)
        """
        os.makedirs(output_dir, exist_ok=True)
        
        page = self.auth.get_page()
        success_count = 0
        fail_count = 0
        errors = []
        
        try:
            response = page.goto(page_url, wait_until='networkidle', timeout=30000)
            
            if response and response.status in [403, 404]:
                page.close()
                return 0, 1, [f"Access error: HTTP {response.status}"]
            
            page.wait_for_timeout(2000)
            
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # Find all PDF links
            pdf_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower():
                    title = link.get_text(strip=True) or "document"
                    pdf_links.append({
                        'url': href if href.startswith('http') else urljoin(page_url, href),
                        'title': title
                    })
            
            page.close()
            
            # Download each PDF
            for pdf_info in pdf_links:
                safe_title = self._safe_filename(pdf_info['title'])
                pdf_path = os.path.join(output_dir, f"{safe_title}.pdf")
                
                success, msg = self.download_file(pdf_info['url'], pdf_path, skip_if_exists=skip_if_exists)
                
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    errors.append(f"{pdf_info['title']}: {msg}")
            
            return success_count, fail_count, errors
            
        except Exception as e:
            page.close()
            return success_count, fail_count + 1, errors + [str(e)]
    
    def find_and_download_audio(self, page_url: str, output_dir: str,
                                 skip_if_exists: bool = True) -> Tuple[int, int, list]:
        """
        Find and download all audio files from a page.
        Returns (success_count, fail_count, errors)
        """
        os.makedirs(output_dir, exist_ok=True)
        
        page = self.auth.get_page()
        success_count = 0
        fail_count = 0
        errors = []
        
        try:
            response = page.goto(page_url, wait_until='networkidle', timeout=30000)
            
            if response and response.status in [403, 404]:
                page.close()
                return 0, 1, [f"Access error: HTTP {response.status}"]
            
            page.wait_for_timeout(2000)
            
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # Find all audio links
            audio_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if any(ext in href.lower() for ext in ['.m4a', '.mp3', '.wav', '.aac']):
                    title = link.get_text(strip=True)
                    if not title or title.lower() == 'download':
                        # Extract from URL
                        filename = href.split('/')[-1].split('?')[0]
                        title = re.sub(r'\.(m4a|mp3|wav|aac)$', '', filename, flags=re.IGNORECASE)
                        title = title.replace('+', ' ').replace('%20', ' ')
                    
                    # Determine extension
                    for ext in ['.m4a', '.mp3', '.wav', '.aac']:
                        if ext in href.lower():
                            audio_links.append({
                                'url': href if href.startswith('http') else urljoin(page_url, href),
                                'title': title,
                                'ext': ext
                            })
                            break
            
            page.close()
            
            # Download each audio file
            for audio_info in audio_links:
                safe_title = self._safe_filename(audio_info['title'])
                audio_path = os.path.join(output_dir, f"{safe_title}{audio_info['ext']}")
                
                success, msg = self.download_file(audio_info['url'], audio_path, skip_if_exists=skip_if_exists)
                
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    errors.append(f"{audio_info['title']}: {msg}")
            
            return success_count, fail_count, errors
            
        except Exception as e:
            page.close()
            return success_count, fail_count + 1, errors + [str(e)]
    
    def _safe_filename(self, name: str) -> str:
        """Convert string to safe filename"""
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        
        if len(safe) > 100:
            safe = safe[:100]
        
        return safe or 'untitled'

