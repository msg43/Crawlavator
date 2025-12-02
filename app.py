"""
Crawlavator - Eurodollar University Batch Downloader
A web app to batch download content from eurodollar.university
"""

import os
import json
import time
import queue
import threading
from flask import Flask, render_template, request, jsonify, Response

from edu_auth import EDUAuth
from edu_scraper import EDUScraper
from download_manager import DownloadManager
from video_extractor import VideoExtractor
from article_downloader import ArticleDownloader
from pdf_downloader import PDFDownloader

app = Flask(__name__)

# Configuration
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
DEFAULT_DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), 'downloads')

# Delays between operations
DOWNLOAD_DELAY = 1  # seconds between items
VIDEO_DOWNLOAD_DELAY = 3  # extra seconds after video downloads

# Global state
progress_queues = {}
indexed_content = {}
auth_instance = None


def get_downloads_dir():
    """Get the configured downloads directory"""
    cfg = load_config()
    download_dir = cfg.get('download_dir', '').strip().strip("'\"")
    
    if download_dir:
        download_dir = os.path.expanduser(download_dir)
        if not os.path.isabs(download_dir):
            download_dir = os.path.abspath(download_dir)
        return download_dir
    
    return DEFAULT_DOWNLOADS_DIR


def load_config():
    """Load configuration from file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_auth() -> EDUAuth:
    """Get or create auth instance"""
    global auth_instance
    if not auth_instance:
        auth_instance = EDUAuth()
    return auth_instance


@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
def config():
    """Get or save configuration"""
    if request.method == 'GET':
        cfg = load_config()
        # Mask password
        if cfg.get('password'):
            cfg['password'] = '••••••••'
        # Check auth status
        auth = get_auth()
        is_auth, _ = auth.check_auth_status()
        cfg['authenticated'] = is_auth
        return jsonify(cfg)
    
    elif request.method == 'POST':
        data = request.json
        cfg = load_config()
        
        if 'email' in data:
            cfg['email'] = data['email']
        if 'password' in data and data['password'] != '••••••••':
            cfg['password'] = data['password']
        if 'download_dir' in data:
            cfg['download_dir'] = data['download_dir']
        
        save_config(cfg)
        return jsonify({'success': True})


@app.route('/api/login', methods=['POST'])
def login():
    """Login to eurodollar.university"""
    cfg = load_config()
    email = cfg.get('email', '')
    password = cfg.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400
    
    try:
        auth = get_auth()
        success, message = auth.login(email, password, headless=False)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/login-interactive', methods=['POST'])
def login_interactive():
    """Open browser for manual login"""
    try:
        auth = get_auth()
        success, message = auth.login_interactive()
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/check-auth')
def check_auth():
    """Check current authentication status"""
    auth = get_auth()
    is_auth, message = auth.check_auth_status()
    return jsonify({
        'authenticated': is_auth,
        'message': message
    })


@app.route('/api/index-content', methods=['POST'])
def index_content():
    """Index all available content"""
    global indexed_content
    
    auth = get_auth()
    is_auth, msg = auth.check_auth_status()
    
    if not is_auth:
        return jsonify({'error': f'Not authenticated: {msg}'}), 401
    
    try:
        scraper = EDUScraper(auth)
        results = scraper.index_all()
        
        indexed_content = {item.id: item.to_dict() for item in scraper.get_all_items()}
        summary = scraper.get_summary()
        
        return jsonify({
            'success': True,
            'summary': summary,
            'items': list(indexed_content.values())
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/content')
def get_content():
    """Get indexed content"""
    return jsonify({
        'items': list(indexed_content.values())
    })


@app.route('/api/download', methods=['POST'])
def start_download():
    """Start downloading selected items"""
    data = request.json
    item_ids = data.get('item_ids', [])
    options = data.get('options', {})
    
    if not item_ids:
        return jsonify({'error': 'No items selected'}), 400
    
    auth = get_auth()
    is_auth, msg = auth.check_auth_status()
    
    if not is_auth:
        return jsonify({'error': f'Not authenticated: {msg}'}), 401
    
    # Create session ID
    import uuid
    session_id = str(uuid.uuid4())
    progress_queues[session_id] = queue.Queue()
    
    # Start download in background
    thread = threading.Thread(
        target=download_worker,
        args=(session_id, item_ids, options, auth)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'session_id': session_id})


def download_worker(session_id, item_ids, options, auth):
    """Background worker for downloads"""
    q = progress_queues.get(session_id)
    if not q:
        return
    
    try:
        downloads_dir = get_downloads_dir()
        os.makedirs(downloads_dir, exist_ok=True)
        
        dm = DownloadManager(downloads_dir)
        video_extractor = VideoExtractor(auth)
        article_dl = ArticleDownloader(auth)
        pdf_dl = PDFDownloader(auth)
        
        total = len(item_ids)
        completed = 0
        skipped = 0
        failed = 0
        
        for i, item_id in enumerate(item_ids):
            try:
                item = indexed_content.get(item_id)
                if not item:
                    q.put({'type': 'warning', 'message': f'Item not found: {item_id}'})
                    failed += 1
                    continue
                
                # Progress update
                progress = ((i + 1) / total) * 100
                q.put({
                    'type': 'progress',
                    'current': i + 1,
                    'total': total,
                    'percent': progress,
                    'message': f'[{i+1}/{total}] {item["title"][:40]}...'
                })
                
                # Check if should download
                if not dm.should_download(item_id):
                    q.put({'type': 'status', 'message': f'Skipping (already complete): {item["title"][:40]}'})
                    skipped += 1
                    continue
                
                # Determine output path
                category_dir = os.path.join(downloads_dir, item['category'])
                if item.get('subcategory'):
                    category_dir = os.path.join(category_dir, item['subcategory'])
                
                safe_title = _safe_filename(item['title'])
                
                # Download based on type
                asset_type = item['asset_type']
                success = False
                message = ""
                
                if asset_type == 'video' and options.get('videos', True):
                    output_dir = os.path.join(category_dir, safe_title)
                    os.makedirs(output_dir, exist_ok=True)
                    output_path = os.path.join(output_dir, 'video.mp4')
                    
                    dm.start_download(item_id, item['title'], item['url'], asset_type, item['category'], output_path)
                    
                    def video_progress(bytes_dl):
                        mb = bytes_dl // 1_000_000
                        if mb % 5 == 0:  # Report every 5MB
                            q.put({'type': 'status', 'message': f'Downloading video: {mb}MB...'})
                    
                    success, message = video_extractor.download_video(
                        item['url'], output_path, progress_callback=video_progress
                    )
                    
                    if success:
                        size = os.path.getsize(output_path)
                        dm.complete_download(item_id, output_path, size)
                    else:
                        dm.fail_download(item_id, message)
                    
                    time.sleep(VIDEO_DOWNLOAD_DELAY)
                
                elif asset_type == 'article' and options.get('articles', True):
                    output_dir = os.path.join(category_dir, safe_title)
                    dm.start_download(item_id, item['title'], item['url'], asset_type, item['category'], output_dir)
                    
                    success, message = article_dl.download_article(item['url'], output_dir)
                    
                    if success:
                        html_path = os.path.join(output_dir, 'article.html')
                        size = os.path.getsize(html_path) if os.path.exists(html_path) else 0
                        dm.complete_download(item_id, output_dir, size)
                    else:
                        if 'Access denied' in message or '403' in message:
                            dm.mark_restricted(item_id, item['title'], item['url'], message)
                        else:
                            dm.fail_download(item_id, message)
                
                elif asset_type == 'pdf' and options.get('pdfs', True):
                    output_path = os.path.join(category_dir, f"{safe_title}.pdf")
                    
                    if item.get('download_url'):
                        dm.start_download(item_id, item['title'], item['url'], asset_type, item['category'], output_path)
                        success, message = pdf_dl.download_file(item['download_url'], output_path)
                    else:
                        dm.start_download(item_id, item['title'], item['url'], asset_type, item['category'], output_path)
                        success, message = pdf_dl.download_daily_briefing(item['url'], item['title'], category_dir)
                    
                    if success:
                        size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                        dm.complete_download(item_id, output_path, size)
                    else:
                        if 'Access denied' in message or '403' in message:
                            dm.mark_restricted(item_id, item['title'], item['url'], message)
                        else:
                            dm.fail_download(item_id, message)
                
                elif asset_type == 'audio' and options.get('audio', True):
                    ext = '.m4a'
                    if item.get('download_url'):
                        for e in ['.m4a', '.mp3', '.wav']:
                            if e in item['download_url'].lower():
                                ext = e
                                break
                    
                    output_path = os.path.join(category_dir, f"{safe_title}{ext}")
                    
                    if item.get('download_url'):
                        dm.start_download(item_id, item['title'], item['url'], asset_type, item['category'], output_path)
                        success, message = pdf_dl.download_file(item['download_url'], output_path)
                    else:
                        skipped += 1
                        continue
                    
                    if success:
                        size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                        dm.complete_download(item_id, output_path, size)
                    else:
                        dm.fail_download(item_id, message)
                
                elif asset_type == 'transcript' and options.get('transcripts', True):
                    output_dir = os.path.join(category_dir, 'transcripts')
                    dm.start_download(item_id, item['title'], item['url'], asset_type, item['category'], output_dir)
                    
                    success, message = article_dl.download_transcript(item['url'], item['title'], output_dir)
                    
                    if success:
                        dm.complete_download(item_id, output_dir, 0)
                    else:
                        dm.fail_download(item_id, message)
                
                else:
                    skipped += 1
                    continue
                
                if success:
                    completed += 1
                    q.put({'type': 'status', 'message': f'✓ {item["title"][:40]}: {message}'})
                else:
                    failed += 1
                    q.put({'type': 'warning', 'message': f'✗ {item["title"][:40]}: {message}'})
                
                time.sleep(DOWNLOAD_DELAY)
                
            except Exception as e:
                failed += 1
                q.put({'type': 'warning', 'message': f'Error: {str(e)}'})
                if item_id in indexed_content:
                    dm.fail_download(item_id, str(e))
        
        # Save final state
        dm.save()
        
        # Summary
        summary = dm.get_summary()
        q.put({
            'type': 'complete',
            'message': f'Download complete! {completed} succeeded, {skipped} skipped, {failed} failed.',
            'folder': downloads_dir,
            'stats': summary
        })
        
    except Exception as e:
        q.put({'type': 'error', 'message': str(e)})
    
    finally:
        time.sleep(2)
        if session_id in progress_queues:
            del progress_queues[session_id]


def _safe_filename(name: str) -> str:
    """Convert string to safe filename"""
    import re
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = re.sub(r'\s+', '_', safe)
    safe = safe.strip('._')
    if len(safe) > 100:
        safe = safe[:100]
    return safe or 'untitled'


@app.route('/api/progress/<session_id>')
def progress(session_id):
    """Server-Sent Events endpoint for download progress"""
    def generate():
        q = progress_queues.get(session_id)
        if not q:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Invalid session'})}\n\n"
            return
        
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get('type') in ('complete', 'error'):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    os.makedirs(DEFAULT_DOWNLOADS_DIR, exist_ok=True)
    
    print("\n" + "="*50)
    print("Crawlavator - Eurodollar University Downloader")
    print("="*50)
    print(f"Open http://localhost:5000 in your browser")
    print("="*50 + "\n")
    
    app.run(debug=True, port=5000, threaded=True)

