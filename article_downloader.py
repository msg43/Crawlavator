"""
Article Downloader
Downloads DDA articles with images from eurodollar.university
"""

import os
import re
import requests
from typing import Tuple, Optional, List
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import Page

from edu_auth import EDUAuth


class ArticleDownloader:
    """Downloads HTML articles with embedded images"""
    
    def __init__(self, auth: EDUAuth):
        self.auth = auth
    
    def download_article(self, article_url: str, output_dir: str,
                         skip_if_exists: bool = True) -> Tuple[bool, str]:
        """
        Download an article page as HTML with all images.
        Returns (success, message)
        """
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        html_path = os.path.join(output_dir, 'article.html')
        images_dir = os.path.join(output_dir, 'images')
        
        # Check if already exists
        if skip_if_exists and os.path.exists(html_path):
            if os.path.getsize(html_path) > 1000:  # More than 1KB
                return True, "Article already downloaded"
        
        page = self.auth.get_page()
        
        try:
            # Navigate to article
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
            
            # Get page HTML
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'lxml')
            
            # Extract main article content
            article = soup.select_one('article, .blog-item, .post-content, main article')
            if not article:
                article = soup.select_one('main, .content')
            
            if not article:
                # Use entire body as fallback
                article = soup.find('body')
            
            if not article:
                page.close()
                return False, "Could not find article content"
            
            # Download and localize images
            os.makedirs(images_dir, exist_ok=True)
            images = article.find_all('img')
            image_count = 0
            
            cookies = self.auth.get_cookies()
            
            for img in images:
                src = img.get('src') or img.get('data-src')
                if not src:
                    continue
                
                # Make absolute URL
                if not src.startswith('http'):
                    src = urljoin(article_url, src)
                
                # Download image
                try:
                    img_response = requests.get(
                        src,
                        cookies=cookies,
                        headers={
                            'User-Agent': 'Mozilla/5.0',
                            'Referer': article_url
                        },
                        timeout=30
                    )
                    
                    if img_response.status_code == 200:
                        # Determine filename
                        ext = self._get_image_extension(src, img_response.headers.get('content-type', ''))
                        img_filename = f"image_{image_count:03d}{ext}"
                        img_path = os.path.join(images_dir, img_filename)
                        
                        with open(img_path, 'wb') as f:
                            f.write(img_response.content)
                        
                        # Update image src in HTML
                        img['src'] = f"images/{img_filename}"
                        if img.get('data-src'):
                            del img['data-src']
                        
                        image_count += 1
                except Exception:
                    pass  # Continue if image fails
            
            # Clean up HTML
            # Remove scripts and unnecessary elements
            for tag in article.find_all(['script', 'noscript', 'iframe']):
                tag.decompose()
            
            # Remove Squarespace-specific elements
            for tag in article.find_all(class_=re.compile(r'sqs-(block-button|cookie|newsletter)')):
                tag.decompose()
            
            # Build standalone HTML
            title = soup.title.string if soup.title else "Article"
            standalone_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem;
            line-height: 1.6;
            color: #333;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        h1, h2, h3 {{
            margin-top: 1.5em;
        }}
        p {{
            margin: 1em 0;
        }}
    </style>
</head>
<body>
    <article>
        {article.decode_contents()}
    </article>
    <footer>
        <p><small>Downloaded from: <a href="{article_url}">{article_url}</a></small></p>
    </footer>
</body>
</html>"""
            
            # Save HTML
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(standalone_html)
            
            page.close()
            return True, f"Article saved with {image_count} images"
            
        except Exception as e:
            page.close()
            return False, f"Download error: {str(e)}"
    
    def _get_image_extension(self, url: str, content_type: str) -> str:
        """Determine image extension from URL or content-type"""
        # Try from URL
        path = urlparse(url).path.lower()
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']:
            if path.endswith(ext):
                return ext
        
        # Try from content-type
        if 'jpeg' in content_type or 'jpg' in content_type:
            return '.jpg'
        elif 'png' in content_type:
            return '.png'
        elif 'gif' in content_type:
            return '.gif'
        elif 'webp' in content_type:
            return '.webp'
        elif 'svg' in content_type:
            return '.svg'
        
        return '.jpg'  # Default
    
    def download_transcript(self, page_url: str, transcript_title: str, 
                            output_dir: str, skip_if_exists: bool = True) -> Tuple[bool, str]:
        """
        Download a transcript by expanding accordion and extracting content.
        Returns (success, message)
        """
        os.makedirs(output_dir, exist_ok=True)
        
        txt_path = os.path.join(output_dir, f"{self._safe_filename(transcript_title)}.txt")
        
        if skip_if_exists and os.path.exists(txt_path):
            if os.path.getsize(txt_path) > 100:
                return True, "Transcript already downloaded"
        
        page = self.auth.get_page()
        
        try:
            response = page.goto(page_url, wait_until='networkidle', timeout=30000)
            
            if response and response.status in [403, 404]:
                page.close()
                return False, f"Access error: HTTP {response.status}"
            
            page.wait_for_timeout(2000)
            
            # Find and click the accordion for this transcript
            try:
                # Try to find accordion button with matching text
                accordion_button = page.locator(f'button:has-text("{transcript_title}")').first
                if accordion_button.count() > 0:
                    accordion_button.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass
            
            # Get expanded content
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # Look for expanded accordion content
            content = None
            
            # Try various selectors
            selectors = [
                f'[aria-labelledby*="{transcript_title}"]',
                '.accordion-content',
                '[class*="accordion"] [class*="content"]',
                '[class*="accordion"] [class*="panel"]',
                '.sqs-block-content',
            ]
            
            for selector in selectors:
                elements = soup.select(selector)
                for elem in elements:
                    text = elem.get_text(strip=True)
                    if len(text) > 500:  # Likely transcript content
                        content = text
                        break
                if content:
                    break
            
            if not content:
                # Try to get all visible text
                main = soup.select_one('main, article, .content')
                if main:
                    content = main.get_text(separator='\n', strip=True)
            
            if not content or len(content) < 100:
                page.close()
                return False, "Could not extract transcript content"
            
            # Save transcript
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"# {transcript_title}\n\n")
                f.write(content)
            
            page.close()
            return True, f"Transcript saved ({len(content)} chars)"
            
        except Exception as e:
            page.close()
            return False, f"Download error: {str(e)}"
    
    def _safe_filename(self, name: str) -> str:
        """Convert string to safe filename"""
        # Remove/replace problematic characters
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('._')
        
        if len(safe) > 100:
            safe = safe[:100]
        
        return safe or 'untitled'

