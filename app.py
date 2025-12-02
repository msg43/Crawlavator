"""
Crawlavator - Multi-Site Batch Downloader
A web app to batch download content from various websites
"""

import os
import json
import time
import queue
import threading
from flask import Flask, render_template, request, jsonify, Response

# Import site plugins - this registers them
from sites import list_sites, get_site, ContentItem
from sites.eurodollar import EurodollarSite
from sites.lexfridman import LexFridmanSite
from shared import DownloadManager

app = Flask(__name__)

# Configuration
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
DEFAULT_DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), 'downloads')

# Delays between operations
DOWNLOAD_DELAY = 1
VIDEO_DOWNLOAD_DELAY = 3

# Global state
progress_queues = {}
indexed_content = {}
site_instances = {}


def get_downloads_dir(site_id: str = None):
    """Get the configured downloads directory for a site"""
    cfg = load_config()
    sites_cfg = cfg.get('sites', {})
    
    if site_id and site_id in sites_cfg:
        download_dir = sites_cfg[site_id].get('download_dir', '').strip().strip("'\"")
        if download_dir:
            download_dir = os.path.expanduser(download_dir)
            if not os.path.isabs(download_dir):
                download_dir = os.path.abspath(download_dir)
            return download_dir
    
    return DEFAULT_DOWNLOADS_DIR


def get_kc_dir(site_id: str = None):
    """Get the knowledge_chipper directory for a site"""
    cfg = load_config()
    sites_cfg = cfg.get('sites', {})
    
    if site_id and site_id in sites_cfg:
        site_cfg = sites_cfg[site_id]
        if site_cfg.get('export_to_kc'):
            kc_dir = site_cfg.get('knowledge_chipper_dir', '').strip().strip("'\"")
            if kc_dir:
                kc_dir = os.path.expanduser(kc_dir)
                if not os.path.isabs(kc_dir):
                    kc_dir = os.path.abspath(kc_dir)
                return kc_dir
    return None


def load_config():
    """Load configuration from file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {'sites': {}, 'active_site': 'eurodollar'}


def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_site_instance(site_id: str):
    """Get or create a site instance"""
    if site_id not in site_instances:
        site_class = get_site(site_id)
        if site_class:
            site_instances[site_id] = site_class()
    return site_instances.get(site_id)


@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')


@app.route('/api/sites')
def get_sites():
    """Get list of available sites"""
    return jsonify(list_sites())


@app.route('/api/config', methods=['GET', 'POST'])
def config():
    """Get or save configuration"""
    if request.method == 'GET':
        cfg = load_config()
        
        # Mask passwords in site configs
        for site_id, site_cfg in cfg.get('sites', {}).items():
            if site_cfg.get('password'):
                site_cfg['password'] = '••••••••'
        
        # Check auth status for active site
        active_site_id = cfg.get('active_site', 'eurodollar')
        site = get_site_instance(active_site_id)
        
        if site and site.REQUIRES_AUTH:
            is_auth, msg = site.check_auth()
            cfg['authenticated'] = is_auth
            cfg['auth_message'] = msg
        else:
            cfg['authenticated'] = True
            cfg['auth_message'] = 'No authentication required'
        
        return jsonify(cfg)
    
    elif request.method == 'POST':
        data = request.json
        cfg = load_config()
        
        # Update active site
        if 'active_site' in data:
            cfg['active_site'] = data['active_site']
        
        # Update site-specific config
        site_id = data.get('site_id') or cfg.get('active_site', 'eurodollar')
        
        if 'sites' not in cfg:
            cfg['sites'] = {}
        if site_id not in cfg['sites']:
            cfg['sites'][site_id] = {}
        
        site_cfg = cfg['sites'][site_id]
        
        # Update fields
        for key in ['email', 'download_dir', 'knowledge_chipper_dir', 'export_to_kc']:
            if key in data:
                site_cfg[key] = data[key]
        
        # Only update password if not masked
        if 'password' in data and data['password'] != '••••••••':
            site_cfg['password'] = data['password']
        
        save_config(cfg)
        return jsonify({'success': True})


@app.route('/api/login', methods=['POST'])
def login():
    """Login to the active site"""
    cfg = load_config()
    active_site_id = cfg.get('active_site', 'eurodollar')
    site_cfg = cfg.get('sites', {}).get(active_site_id, {})
    
    site = get_site_instance(active_site_id)
    if not site:
        return jsonify({'success': False, 'error': 'Site not found'}), 400
    
    if not site.REQUIRES_AUTH:
        return jsonify({'success': True, 'message': 'No authentication required'})
    
    email = site_cfg.get('email', '')
    password = site_cfg.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400
    
    try:
        success, message = site.login(email=email, password=password)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/login-interactive', methods=['POST'])
def login_interactive():
    """Open browser for manual login"""
    cfg = load_config()
    active_site_id = cfg.get('active_site', 'eurodollar')
    
    site = get_site_instance(active_site_id)
    if not site:
        return jsonify({'success': False, 'error': 'Site not found'}), 400
    
    if not site.REQUIRES_AUTH:
        return jsonify({'success': True, 'message': 'No authentication required'})
    
    try:
        success, message = site.login(interactive=True)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/check-auth')
def check_auth():
    """Check current authentication status"""
    cfg = load_config()
    active_site_id = cfg.get('active_site', 'eurodollar')
    
    site = get_site_instance(active_site_id)
    if not site:
        return jsonify({'authenticated': False, 'message': 'Site not found'})
    
    if not site.REQUIRES_AUTH:
        return jsonify({'authenticated': True, 'message': 'No authentication required'})
    
    is_auth, message = site.check_auth()
    return jsonify({
        'authenticated': is_auth,
        'message': message
    })


@app.route('/api/index-content', methods=['POST'])
def index_content():
    """Index all available content for the active site"""
    global indexed_content
    
    cfg = load_config()
    active_site_id = cfg.get('active_site', 'eurodollar')
    
    site = get_site_instance(active_site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 400
    
    if site.REQUIRES_AUTH:
        is_auth, msg = site.check_auth()
        if not is_auth:
            return jsonify({'error': f'Not authenticated: {msg}'}), 401
    
    try:
        items = site.index_content()
        
        # Store indexed content
        indexed_content = {item.id: item.to_dict() for item in items}
        
        # Get summary if available
        summary = {}
        if hasattr(site, 'get_summary'):
            summary = site.get_summary()
        
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
    
    cfg = load_config()
    active_site_id = cfg.get('active_site', 'eurodollar')
    
    site = get_site_instance(active_site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 400
    
    if site.REQUIRES_AUTH:
        is_auth, msg = site.check_auth()
        if not is_auth:
            return jsonify({'error': f'Not authenticated: {msg}'}), 401
    
    # Create session ID
    import uuid
    session_id = str(uuid.uuid4())
    progress_queues[session_id] = queue.Queue()
    
    # Start download in background
    thread = threading.Thread(
        target=download_worker,
        args=(session_id, item_ids, options, active_site_id)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'session_id': session_id})


def download_worker(session_id, item_ids, options, site_id):
    """Background worker for downloads"""
    q = progress_queues.get(session_id)
    if not q:
        return
    
    site = get_site_instance(site_id)
    if not site:
        q.put({'type': 'error', 'message': 'Site not found'})
        return
    
    try:
        downloads_dir = get_downloads_dir(site_id)
        os.makedirs(downloads_dir, exist_ok=True)
        
        dm = DownloadManager(downloads_dir)
        
        # Check for knowledge_chipper export
        kc_dir = get_kc_dir(site_id)
        if kc_dir:
            os.makedirs(kc_dir, exist_ok=True)
        
        total = len(item_ids)
        completed = 0
        skipped = 0
        failed = 0
        
        for i, item_id in enumerate(item_ids):
            try:
                item_dict = indexed_content.get(item_id)
                if not item_dict:
                    q.put({'type': 'warning', 'message': f'Item not found: {item_id}'})
                    failed += 1
                    continue
                
                # Convert dict back to ContentItem
                item = ContentItem(**item_dict)
                
                # Progress update
                progress = ((i + 1) / total) * 100
                q.put({
                    'type': 'progress',
                    'current': i + 1,
                    'total': total,
                    'percent': progress,
                    'message': f'[{i+1}/{total}] {item.title[:40]}...'
                })
                
                # Check if should download
                if not dm.should_download(item_id):
                    q.put({'type': 'status', 'message': f'Skipping (already complete): {item.title[:40]}'})
                    skipped += 1
                    continue
                
                # Determine output path
                category_dir = os.path.join(downloads_dir, item.category)
                if item.subcategory:
                    category_dir = os.path.join(category_dir, item.subcategory)
                
                safe_title = _safe_filename(item.title)
                
                # Create output directory
                if item.asset_type in ['video', 'article']:
                    output_dir = os.path.join(category_dir, safe_title)
                else:
                    output_dir = category_dir
                os.makedirs(output_dir, exist_ok=True)
                
                # Start tracking
                dm.start_download(item_id, item.title, item.url, item.asset_type, item.category, output_dir)
                
                # Download
                success, message = site.download_item(item, output_dir)
                
                if success:
                    dm.complete_download(item_id, output_dir, 0)
                    completed += 1
                    q.put({'type': 'status', 'message': f'✓ {item.title[:40]}: {message}'})
                    
                    # Export to knowledge_chipper if enabled
                    if kc_dir and item.asset_type == 'transcript':
                        try:
                            export_to_knowledge_chipper(item, output_dir, kc_dir)
                        except Exception as e:
                            q.put({'type': 'warning', 'message': f'KC export failed: {str(e)}'})
                else:
                    if 'Access denied' in message or '403' in message:
                        dm.mark_restricted(item_id, item.title, item.url, message)
                    else:
                        dm.fail_download(item_id, message)
                    failed += 1
                    q.put({'type': 'warning', 'message': f'✗ {item.title[:40]}: {message}'})
                
                # Delay between downloads
                if item.asset_type == 'video':
                    time.sleep(VIDEO_DOWNLOAD_DELAY)
                else:
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


def export_to_knowledge_chipper(item: ContentItem, source_dir: str, kc_dir: str):
    """Export transcript to knowledge_chipper format"""
    # This will be implemented when we add transcript parsing
    pass


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
    print("Crawlavator - Multi-Site Batch Downloader")
    print("="*50)
    print(f"Open http://localhost:5001 in your browser")
    print("="*50 + "\n")
    
    app.run(debug=True, port=5001, threaded=True)
