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
from sites.conversationswithtyler import ConversationsWithTylerSite
from sites.private_rss import PrivateRSSSite
from sites.invest_like_best import InvestLikeBestSite
from sites.macrovoices import MacroVoicesSite
from sites.peter_zeihan import PeterZeihanSite
from sites.ezra_klein import EzraKleinSite
from sites.odd_lots import OddLotsSite
from sites.hidden_forces import HiddenForcesSite
from sites.excess_returns import ExcessReturnsSite
from sites.dwarkesh import DwarkeshSite
from sites.fareed_zakaria import FareedZakariaSite
from sites.bigthink import BigThinkSite
from shared import DownloadManager
from shared.sync_manager import SyncManager
import feedparser

app = Flask(__name__)

# Configuration
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
DEFAULT_DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), 'downloads')
PRIVATE_FEEDS_FILE = os.path.join(os.path.dirname(__file__), '.private', 'rss_feeds.json')

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


@app.route('/api/download-new', methods=['POST'])
def download_new():
    """Download only new items for a single site (not already local)"""
    try:
        data = request.json or {}
        site_id = data.get('site_id')
        search_dir = data.get('search_dir', DEFAULT_DOWNLOADS_DIR)
        
        if not site_id:
            return jsonify({'error': 'No site_id provided'}), 400
        
        # Create session ID
        import uuid
        session_id = str(uuid.uuid4())
        progress_queues[session_id] = queue.Queue()
        
        # Start download in background
        thread = threading.Thread(
            target=download_new_worker,
            args=(session_id, site_id, search_dir)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'session_id': session_id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


def download_new_worker(session_id, site_id, search_dir):
    """Background worker for downloading only new items"""
    import time as time_module
    q = progress_queues.get(session_id)
    if not q:
        return
    
    try:
        q.put({'type': 'status', 'message': 'Getting indexed content...'})
        
        # Get indexed content for this site
        if site_id not in indexed_content or not indexed_content[site_id]:
            q.put({'type': 'error', 'message': 'No indexed content found. Please scan content first.'})
            return
        
        items = indexed_content[site_id]
        
        # Use SyncManager to find what's already local
        q.put({'type': 'status', 'message': f'Scanning {search_dir} for existing content...'})
        sync_manager = SyncManager(DEFAULT_DOWNLOADS_DIR)
        
        site = get_site_instance(site_id)
        if not site:
            q.put({'type': 'error', 'message': 'Site not found'})
            return
        
        site_name = site.SITE_NAME
        sync_result = sync_manager.sync_source(site_id, site_name, items, search_dir)
        
        new_items = sync_result.get('new_items_full', [])
        
        q.put({
            'type': 'info',
            'message': f'Found {sync_result["indexed"]} episodes total'
        })
        q.put({
            'type': 'info',
            'message': f'Already have {sync_result["local"]} episodes locally'
        })
        q.put({
            'type': 'success',
            'message': f'Will download {len(new_items)} new episodes'
        })
        
        if not new_items:
            q.put({
                'type': 'complete',
                'message': '✓ Everything is up to date!',
                'summary': {
                    'indexed': sync_result['indexed'],
                    'local': sync_result['local'],
                    'downloaded': 0
                }
            })
            return
        
        # Create site-specific folder
        site_folder = os.path.join(os.path.expanduser(search_dir), site_name)
        os.makedirs(site_folder, exist_ok=True)
        
        # Download new items
        downloaded_count = 0
        download_errors = 0
        
        for item_idx, item in enumerate(new_items, 1):
            try:
                q.put({
                    'type': 'progress',
                    'message': f'[{item_idx}/{len(new_items)}] {item.title[:50]}...',
                    'percent': (item_idx / len(new_items)) * 100
                })
                
                site.download_item(item, site_folder)
                downloaded_count += 1
                
            except Exception as e:
                q.put({
                    'type': 'warning',
                    'message': f'⚠️ Error: {item.title[:30]}: {str(e)[:50]}'
                })
                download_errors += 1
        
        # Send completion message
        q.put({
            'type': 'complete',
            'message': f'✓ Downloaded {downloaded_count} new episodes!',
            'summary': {
                'indexed': sync_result['indexed'],
                'local': sync_result['local'],
                'downloaded': downloaded_count,
                'errors': download_errors
            }
        })
        
    except Exception as e:
        q.put({'type': 'error', 'message': f'Error: {str(e)}'})
    
    finally:
        time_module.sleep(2)
        if session_id in progress_queues:
            del progress_queues[session_id]


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
                
                # Create output directory - each item gets its own folder
                output_dir = os.path.join(category_dir, safe_title)
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


@app.route('/api/private-feeds', methods=['GET'])
def get_private_feeds():
    """Get all private RSS feeds"""
    try:
        if os.path.exists(PRIVATE_FEEDS_FILE):
            with open(PRIVATE_FEEDS_FILE, 'r') as f:
                data = json.load(f)
                return jsonify(data)
        return jsonify({'feeds': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/private-feeds', methods=['POST'])
def add_private_feed():
    """Add a new private RSS feed"""
    try:
        data = request.json
        
        # Validate required fields
        if not data.get('name') or not data.get('url'):
            return jsonify({'error': 'Name and URL are required'}), 400
        
        # Validate RSS feed URL
        try:
            feed = feedparser.parse(data['url'])
            if not feed.entries:
                return jsonify({'error': 'Invalid RSS feed or no episodes found'}), 400
        except Exception as e:
            return jsonify({'error': f'Failed to parse RSS feed: {str(e)}'}), 400
        
        # Load existing feeds
        feeds_data = {'feeds': []}
        if os.path.exists(PRIVATE_FEEDS_FILE):
            with open(PRIVATE_FEEDS_FILE, 'r') as f:
                feeds_data = json.load(f)
        
        # Generate unique ID
        feed_id = data['name'].lower().replace(' ', '_').replace('-', '_')
        feed_id = ''.join(c for c in feed_id if c.isalnum() or c == '_')
        
        # Check for duplicate ID
        existing_ids = [f['id'] for f in feeds_data['feeds']]
        if feed_id in existing_ids:
            counter = 1
            while f"{feed_id}_{counter}" in existing_ids:
                counter += 1
            feed_id = f"{feed_id}_{counter}"
        
        # Create feed entry
        new_feed = {
            'id': feed_id,
            'name': data['name'],
            'url': data['url'],
            'author': data.get('author', ''),
            'added_date': time.strftime('%Y-%m-%d')
        }
        
        feeds_data['feeds'].append(new_feed)
        
        # Save to file
        os.makedirs(os.path.dirname(PRIVATE_FEEDS_FILE), exist_ok=True)
        with open(PRIVATE_FEEDS_FILE, 'w') as f:
            json.dump(feeds_data, f, indent=2)
        
        return jsonify({'success': True, 'feed': new_feed})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/private-feeds/<feed_id>', methods=['DELETE'])
def delete_private_feed(feed_id):
    """Delete a private RSS feed"""
    try:
        if not os.path.exists(PRIVATE_FEEDS_FILE):
            return jsonify({'error': 'No feeds found'}), 404
        
        with open(PRIVATE_FEEDS_FILE, 'r') as f:
            feeds_data = json.load(f)
        
        # Filter out the feed to delete
        original_count = len(feeds_data['feeds'])
        feeds_data['feeds'] = [f for f in feeds_data['feeds'] if f['id'] != feed_id]
        
        if len(feeds_data['feeds']) == original_count:
            return jsonify({'error': 'Feed not found'}), 404
        
        # Save updated list
        with open(PRIVATE_FEEDS_FILE, 'w') as f:
            json.dump(feeds_data, f, indent=2)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/private-feeds/<feed_id>', methods=['PUT'])
def update_private_feed(feed_id):
    """Update a private RSS feed"""
    try:
        data = request.json
        
        if not os.path.exists(PRIVATE_FEEDS_FILE):
            return jsonify({'error': 'No feeds found'}), 404
        
        with open(PRIVATE_FEEDS_FILE, 'r') as f:
            feeds_data = json.load(f)
        
        # Find and update the feed
        feed_found = False
        for feed in feeds_data['feeds']:
            if feed['id'] == feed_id:
                feed_found = True
                if 'name' in data:
                    feed['name'] = data['name']
                if 'url' in data:
                    # Validate new URL
                    try:
                        test_feed = feedparser.parse(data['url'])
                        if not test_feed.entries:
                            return jsonify({'error': 'Invalid RSS feed'}), 400
                    except:
                        return jsonify({'error': 'Failed to parse RSS feed'}), 400
                    feed['url'] = data['url']
                if 'author' in data:
                    feed['author'] = data['author']
                break
        
        if not feed_found:
            return jsonify({'error': 'Feed not found'}), 404
        
        # Save updated list
        with open(PRIVATE_FEEDS_FILE, 'w') as f:
            json.dump(feeds_data, f, indent=2)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync-all', methods=['POST'])
def sync_all_sources():
    """Start sync all sources in background with progress updates"""
    try:
        data = request.json or {}
        search_dir = data.get('search_dir', DEFAULT_DOWNLOADS_DIR)
        
        # Create session ID
        import uuid
        session_id = str(uuid.uuid4())
        progress_queues[session_id] = queue.Queue()
        
        # Start sync in background
        thread = threading.Thread(
            target=sync_all_worker,
            args=(session_id, search_dir)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'session_id': session_id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def sync_all_worker(session_id, search_dir):
    """Background worker for sync all operation"""
    import time as time_module
    q = progress_queues.get(session_id)
    if not q:
        return
    
    try:
        start_time = time_module.time()
        
        # Get all available sites
        available_sites = list_sites()
        
        # Move Eurodollar University to the end (it's slow, so process it last)
        eurodollar_site = None
        other_sites = []
        for site in available_sites:
            if site['id'] == 'eurodollar':
                eurodollar_site = site
            else:
                other_sites.append(site)
        
        if eurodollar_site:
            available_sites = other_sites + [eurodollar_site]
        
        sync_manager = SyncManager(DEFAULT_DOWNLOADS_DIR)
        
        results = {
            'sources_checked': 0,
            'new_items': 0,
            'skipped': 0,
            'errors': 0,
            'details': [],
            'search_dir': search_dir
        }
        
        total_sites = len(available_sites)
        failed_sites = []  # Track sites that failed or timed out for retry
        
        q.put({
            'type': 'status',
            'message': f'Starting sync for {total_sites} sources...'
        })
        
        # Sync each site - automatically index if needed
        for idx, site_info in enumerate(available_sites, 1):
            site_id = site_info['id']
            site_name = site_info['name']
            channel_start_time = time_module.time()
            
            q.put({
                'type': 'status',
                'message': f'[{idx}/{total_sites}] Processing {site_name}...',
                'current_source': site_name,
                'source_progress': idx,
                'total_sources': total_sites
            })
            
            try:
                # Get site instance
                site = get_site_instance(site_id)
                if not site:
                    continue
                
                # Automatically index content for this site if not already indexed
                items = []
                if site_id in indexed_content and indexed_content[site_id]:
                    # Use cached index
                    items = indexed_content[site_id]
                    q.put({
                        'type': 'info',
                        'message': f'  Using cached index ({len(items)} episodes)'
                    })
                else:
                    # Auto-index this source
                    q.put({
                        'type': 'info',
                        'message': f'  Indexing {site_name}...'
                    })
                    
                    try:
                        items = site.index_content(progress_callback=lambda msg: q.put({
                            'type': 'info',
                            'message': f'    {msg}'
                        }))
                        # Cache it for future use
                        indexed_content[site_id] = items
                        q.put({
                            'type': 'info',
                            'message': f'  ✓ Indexed {len(items)} episodes'
                        })
                    except Exception as e:
                        q.put({
                            'type': 'error',
                            'message': f'  Failed to index {site_name}: {e}'
                        })
                        continue
                
                if items:
                    # Sync this source with user-specified search directory
                    sync_result = sync_manager.sync_source(site_id, site_name, items, search_dir)
                    
                    # Download new items
                    new_items_to_download = sync_result.get('new_items_full', [])
                    downloaded_count = 0
                    download_errors = 0
                    
                    if new_items_to_download:
                        # For Private RSS, create individual feed folders; for others, use site name
                        if site_id == 'private_rss':
                            # Group items by feed (subcategory)
                            items_by_feed = {}
                            for item in new_items_to_download:
                                feed_name = item.subcategory or 'Unknown Feed'
                                if feed_name not in items_by_feed:
                                    items_by_feed[feed_name] = []
                                items_by_feed[feed_name].append(item)
                            
                            # Download each feed to its own folder
                            for feed_name, feed_items in items_by_feed.items():
                                feed_folder = os.path.join(os.path.expanduser(search_dir), feed_name)
                                os.makedirs(feed_folder, exist_ok=True)
                                
                                for item_idx, item in enumerate(feed_items, 1):
                                    # Check timeout
                                    if time_module.time() - channel_start_time > 60 and downloaded_count == 0:
                                        q.put({
                                            'type': 'warning',
                                            'message': f'  ⏱️ Timeout: {site_name} stuck for 60s. Skipping for now...'
                                        })
                                        failed_sites.append({
                                            'site_info': site_info,
                                            'reason': 'timeout',
                                            'items': items,
                                            'sync_result': sync_result
                                        })
                                        break
                                    
                                    try:
                                        q.put({
                                            'type': 'progress',
                                            'message': f'  [{downloaded_count + 1}/{len(new_items_to_download)}] {feed_name}: {item.title[:30]}...',
                                            'percent': ((downloaded_count + 1) / len(new_items_to_download)) * 100
                                        })
                                        
                                        site.download_item(item, feed_folder)
                                        downloaded_count += 1
                                        channel_start_time = time_module.time()
                                        
                                    except Exception as e:
                                        q.put({
                                            'type': 'warning',
                                            'message': f'  ⚠️ Error: {item.title[:30]}: {str(e)[:50]}'
                                        })
                                        download_errors += 1
                                        
                                        if download_errors > 3 and downloaded_count == 0:
                                            q.put({
                                                'type': 'warning',
                                                'message': f'  Multiple errors for {site_name}. Skipping remaining...'
                                            })
                                            failed_sites.append({
                                                'site_info': site_info,
                                                'reason': 'multiple_errors',
                                                'items': items,
                                                'sync_result': sync_result
                                            })
                                            break
                            
                            # Skip the normal download loop for private RSS
                            new_items_to_download = []
                        else:
                            # Create site-specific folder in the search directory
                            site_folder = os.path.join(os.path.expanduser(search_dir), site_name)
                            os.makedirs(site_folder, exist_ok=True)
                        
                        q.put({
                            'type': 'info',
                            'message': f'  📥 Downloading {len(new_items_to_download)} new episodes...'
                        })
                        
                        for item_idx, item in enumerate(new_items_to_download, 1):
                            # Check if this channel has been stuck for 60 seconds
                            if time_module.time() - channel_start_time > 60 and downloaded_count == 0:
                                q.put({
                                    'type': 'warning',
                                    'message': f'  ⏱️ Timeout: {site_name} stuck for 60s with no downloads. Skipping for now...'
                                })
                                failed_sites.append({
                                    'site_info': site_info,
                                    'reason': 'timeout',
                                    'items': items,
                                    'sync_result': sync_result
                                })
                                break
                            
                            try:
                                # Download the item
                                q.put({
                                    'type': 'progress',
                                    'message': f'  [{item_idx}/{len(new_items_to_download)}] {item.title[:40]}...',
                                    'percent': (item_idx / len(new_items_to_download)) * 100
                                })
                                
                                site.download_item(item, site_folder)
                                downloaded_count += 1
                                channel_start_time = time_module.time()  # Reset timer on successful download
                                
                            except Exception as e:
                                q.put({
                                    'type': 'warning',
                                    'message': f'  ⚠️ Error: {item.title[:30]}: {str(e)[:50]}'
                                })
                                download_errors += 1
                                
                                # If all downloads are failing, might be a systemic issue with this channel
                                if download_errors > 3 and downloaded_count == 0:
                                    q.put({
                                        'type': 'warning',
                                        'message': f'  Multiple errors for {site_name}. Skipping remaining items for now...'
                                    })
                                    failed_sites.append({
                                        'site_info': site_info,
                                        'reason': 'multiple_errors',
                                        'items': items,
                                        'sync_result': sync_result
                                    })
                                    break
                        
                        q.put({
                            'type': 'success',
                            'message': f'  ✓ {site_name}: Downloaded {downloaded_count} episodes'
                        })
                    else:
                        q.put({
                            'type': 'info',
                            'message': f'  ✓ {site_name}: Up to date (no new episodes)'
                        })
                    
                    # Update results
                    sync_result_summary = {
                        'source': sync_result['source'],
                        'source_name': sync_result['source_name'],
                        'indexed': sync_result['indexed'],
                        'local': sync_result['local'],
                        'new': sync_result['new'],
                        'downloaded': downloaded_count,
                        'download_errors': download_errors,
                        'new_items_preview': sync_result.get('new_items_preview', [])
                    }
                    
                    results['details'].append(sync_result_summary)
                    results['sources_checked'] += 1
                    results['new_items'] += downloaded_count
                    results['skipped'] += sync_result['local']
                    results['errors'] += download_errors
                    
            except Exception as e:
                q.put({
                    'type': 'error',
                    'message': f'  ❌ Error syncing {site_name}: {str(e)}'
                })
                results['errors'] += 1
                results['details'].append({
                    'source': site_id,
                    'source_name': site_name,
                    'error': str(e)
                })
                failed_sites.append({
                    'site_info': site_info,
                    'reason': 'exception',
                    'error': str(e)
                })
        
        # Retry failed sites
        if failed_sites:
            q.put({
                'type': 'status',
                'message': f'\n🔄 Retrying {len(failed_sites)} failed sources...'
            })
            
            for retry_idx, failed_site in enumerate(failed_sites, 1):
                site_info = failed_site['site_info']
                site_id = site_info['id']
                site_name = site_info['name']
                
                q.put({
                    'type': 'status',
                    'message': f'[Retry {retry_idx}/{len(failed_sites)}] Retrying {site_name}...'
                })
                
                try:
                    site = get_site_instance(site_id)
                    if not site:
                        continue
                    
                    # If we have cached items and sync_result, use them
                    if 'items' in failed_site and 'sync_result' in failed_site:
                        items = failed_site['items']
                        sync_result = failed_site['sync_result']
                        new_items_to_download = sync_result.get('new_items_full', [])
                        
                        if new_items_to_download:
                            site_folder = os.path.join(os.path.expanduser(search_dir), site_name)
                            os.makedirs(site_folder, exist_ok=True)
                            
                            downloaded_count = 0
                            download_errors = 0
                            channel_start_time = time_module.time()
                            
                            for item_idx, item in enumerate(new_items_to_download, 1):
                                # Timeout check for retry too
                                if time_module.time() - channel_start_time > 60 and downloaded_count == 0:
                                    q.put({
                                        'type': 'error',
                                        'message': f'  ❌ {site_name} still timing out. Giving up.'
                                    })
                                    break
                                
                                try:
                                    q.put({
                                        'type': 'progress',
                                        'message': f'  [{item_idx}/{len(new_items_to_download)}] {item.title[:40]}...',
                                        'percent': (item_idx / len(new_items_to_download)) * 100
                                    })
                                    
                                    site.download_item(item, site_folder)
                                    downloaded_count += 1
                                    channel_start_time = time_module.time()
                                    
                                except Exception as e:
                                    download_errors += 1
                                    if download_errors > 3 and downloaded_count == 0:
                                        q.put({
                                            'type': 'error',
                                            'message': f'  ❌ {site_name} still failing. Giving up.'
                                        })
                                        break
                            
                            if downloaded_count > 0:
                                q.put({
                                    'type': 'success',
                                    'message': f'  ✓ Retry successful: {site_name} downloaded {downloaded_count} episodes'
                                })
                                
                                # Update results
                                sync_result_summary = {
                                    'source': sync_result['source'],
                                    'source_name': sync_result['source_name'],
                                    'indexed': sync_result['indexed'],
                                    'local': sync_result['local'],
                                    'new': sync_result['new'],
                                    'downloaded': downloaded_count,
                                    'download_errors': download_errors,
                                    'new_items_preview': sync_result.get('new_items_preview', [])
                                }
                                
                                results['details'].append(sync_result_summary)
                                results['sources_checked'] += 1
                                results['new_items'] += downloaded_count
                                results['errors'] += download_errors
                            else:
                                q.put({
                                    'type': 'error',
                                    'message': f'  ❌ {site_name} retry failed - no episodes downloaded'
                                })
                                results['errors'] += 1
                    
                except Exception as e:
                    q.put({
                        'type': 'error',
                        'message': f'  ❌ Error retrying {site_name}: {str(e)}'
                    })
                    results['errors'] += 1
        
        # Calculate duration
        duration = int(time_module.time() - start_time)
        results['duration_seconds'] = duration
        
        # Log the sync operation
        sync_manager.log_sync_operation(results)
        
        # Send final summary
        q.put({
            'type': 'complete',
            'message': f'✓ Sync complete! Downloaded {results["new_items"]} episodes in {duration}s',
            'results': results
        })
        
    except Exception as e:
        q.put({'type': 'error', 'message': f'Sync failed: {str(e)}'})
    
    finally:
        time_module.sleep(2)
        if session_id in progress_queues:
            del progress_queues[session_id]


if __name__ == '__main__':
    os.makedirs(DEFAULT_DOWNLOADS_DIR, exist_ok=True)
    
    print("\n" + "="*50)
    print("Crawlavator - Multi-Site Batch Downloader")
    print("="*50)
    print(f"Open http://localhost:5002 in your browser")
    print("="*50 + "\n")
    
    app.run(debug=True, port=5002, threaded=True)
