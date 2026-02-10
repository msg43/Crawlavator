# Crawlavator Multi-Podcast Implementation Status

## ✅ Phase 0: Core Features (COMPLETED)

### Dependencies
- ✅ Added `feedparser>=6.0.0` to requirements.txt
- ✅ Added `yt-dlp>=2023.0.0` to requirements.txt  
- ✅ Updated .gitignore to include `.private/` directory

### Generic Private RSS Feed Feature
- ✅ Created `.private/` directory with `rss_feeds.json`
- ✅ Created `sites/private_rss/__init__.py` plugin
- ✅ Added API routes in `app.py`:
  - `GET /api/private-feeds` - List all private feeds
  - `POST /api/private-feeds` - Add new private feed
  - `DELETE /api/private-feeds/<id>` - Delete feed
  - `PUT /api/private-feeds/<id>` - Update feed
- ✅ Added UI tab in `templates/index.html`
- ✅ Added CSS styles in `static/style.css`
- ✅ Added JavaScript functionality in `static/app.js`
- ✅ Feed validation using feedparser before saving
- ✅ Security notice displayed in UI

**Usage:** Users can add any private RSS feed URL (Sam Harris, Patreon, Supercast, etc.) through the UI.

### Sync All Sources Feature
- ✅ Created `shared/sync_manager.py`
- ✅ Added `POST /api/sync-all` endpoint in `app.py`
- ✅ Recursive content comparison logic
- ✅ JSONL log file format (`downloads/sync_log.jsonl`)
- ✅ UI tab for sync operations
- ✅ Summary modal displaying sync results
- ✅ Tracks: sources checked, new items, skipped items, errors

**Usage:** Click "Sync All" tab, then "Start Sync" to download only new content from all enabled sources.

## ✅ Phase 1: Tier 1 Podcast Plugins (PARTIAL)

### Completed Plugins

#### 1. Invest Like the Best ✅
- **File:** `sites/invest_like_best/__init__.py`
- **RSS Feed:** https://investlikethebest.libsyn.com/rss
- **Features:** 
  - Indexes from RSS feed
  - Attempts to scrape transcripts from joincolossus.com
  - Falls back to audio download if no transcript
- **Asset Types:** transcript (preferred), audio (fallback)

#### 2. MacroVoices ✅
- **File:** `sites/macrovoices/__init__.py`
- **RSS Feed:** https://www.macrovoices.com/podcast-rss-feed
- **Features:**
  - Indexes from RSS feed
  - Scrapes transcripts from macrovoices.com
  - Falls back to audio download
- **Asset Types:** transcript (preferred), audio (fallback)

### Remaining Tier 1 Plugins (TODO)

#### 3. The Ezra Klein Show
- **RSS Feed:** Available via NYT
- **Transcripts:** Available on nytimes.com
- **Implementation:** RSS + web scraping for transcripts

#### 4. Odd Lots
- **RSS Feed:** Available via Bloomberg
- **Transcripts:** Available on bloomberg.com
- **Implementation:** RSS + web scraping for transcripts

## 🔄 Phase 2: Tier 2 Podcast Plugins (TODO)

### 5. Peter Zeihan
- **RSS Feed:** https://media.rss.com/zeihan/feed.xml
- **Transcripts:** Available on tapesearch.com or Patreon
- **Implementation:** RSS for audio, external transcript source or use Private RSS feature for Patreon

### 6. Fareed Zakaria GPS
- **RSS Feed:** Available via CNN
- **Transcripts:** Available on CNN website
- **Implementation:** RSS + CNN transcript scraping

### 7. Hidden Forces
- **RSS Feed:** Available (free episodes)
- **Transcripts:** Some on hiddenforces.io
- **Implementation:** RSS + web scraping, premium via Private RSS

### 8. Curt Jaimungal (Theories of Everything)
- **Source:** YouTube primarily
- **Transcripts:** YouTube auto-captions
- **Implementation:** yt-dlp for caption extraction

## 📋 Phase 3: Research & Advanced Features (TODO)

### Tier 4 Sources (Needs Research)
- Joseph Goldstein - Dharma Seed lectures
- Verdad Capital - research/podcasts  
- Luke Gromen - (guest on other shows, not own podcast)
- Lyn Alden - (guest on other shows, not own podcast)
- Bridgewater - unclear if podcast exists
- Infranomics - unclear
- Interesting Times w/ Ross Douthat - unclear
- Matt Levine - written content (Money Stuff newsletter), not podcast

### Patreon OAuth Plugin (Advanced)
For accessing authenticated Patreon content like Peter Zeihan transcripts:
- Browser automation with Playwright
- Google OAuth handling
- Session persistence
- HTML parsing for collections

## 🏗️ Architecture Summary

### Plugin System
All plugins implement `BaseSite` interface from `sites/__init__.py`:
- `SITE_ID`: Unique identifier
- `SITE_NAME`: Display name
- `REQUIRES_AUTH`: Boolean
- `ASSET_TYPES`: List of supported types
- `CATEGORIES`: List of categories
- Methods: `index_content()`, `download_item()`, `check_auth()`, `login()`

### Content Flow
1. User selects site from dropdown
2. Clicks "Scan Content" → calls `index_content()`
3. Content displayed in table
4. User selects items to download
5. Clicks "Download" → calls `download_item()` for each
6. Downloads saved to `downloads/` with manifest tracking

### Sync Flow
1. User clicks "Sync All" tab
2. Clicks "Start Sync"
3. Backend:
   - Loads all indexed content per source
   - Scans local directories recursively
   - Compares indexed vs. local
   - Downloads only new items
   - Logs to `sync_log.jsonl`
4. UI displays summary

## 📦 Installation & Setup

### Install New Dependencies
```bash
pip install feedparser yt-dlp
```

### Test Private RSS Feature
1. Start app: `python app.py`
2. Go to "Private RSS Feeds" tab
3. Add a test RSS feed URL
4. Verify it validates and saves to `.private/rss_feeds.json`
5. Switch to "Content" tab, select "private_rss" from dropdown
6. Click "Scan Content" to index the feed

### Test Sync Feature
1. Have at least one source indexed (e.g., Lex Fridman)
2. Download some content
3. Go to "Sync All" tab
4. Click "Start Sync"
5. Should show "0 new" for already downloaded content
6. Check `downloads/sync_log.jsonl` for log entry

## 🎯 Next Steps for Completion

1. **Create remaining Tier 1 plugins** (Ezra Klein, Odd Lots)
2. **Create Tier 2 plugins** (Peter Zeihan, Fareed Zakaria, Hidden Forces, Curt Jaimungal)
3. **Research Tier 4 sources** to determine feasibility
4. **Test all plugins** end-to-end
5. **Update UI** to include all new sources in dropdown
6. **Documentation** for each plugin's specific requirements

## 🔧 Template for New Plugins

See `sites/invest_like_best/__init__.py` or `sites/macrovoices/__init__.py` as templates.

Basic structure:
```python
from .. import BaseSite, ContentItem, register_site

@register_site
class YourSite(BaseSite):
    SITE_ID = "your_site_id"
    SITE_NAME = "Your Site Name"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript", "audio"]
    CATEGORIES = ["podcast"]
    
    def index_content(self, progress_callback=None):
        # Parse RSS or scrape website
        # Return list of ContentItem objects
        
    def download_item(self, item, output_dir, progress_callback=None):
        # Download transcript or audio
        # Return (success: bool, message: str)
```

Don't forget to import in `app.py`!

## 🎉 Achievements

- ✅ Generic Private RSS feed manager (works for ALL paid podcasts)
- ✅ Smart sync system (downloads only new content)
- ✅ Tabbed UI interface
- ✅ 2 complete Tier 1 plugins with transcript scraping
- ✅ Secure storage for private URLs
- ✅ Activity logging
- ✅ Clean plugin architecture for easy expansion

This implementation provides a solid foundation for adding any podcast source going forward!

