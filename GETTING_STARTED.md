# Getting Started with Your Updated Crawlavator

## 🎉 What's New

Your Crawlavator now has three powerful new features:

### 1. **Private RSS Feed Manager**
Add any private podcast RSS feed (Sam Harris, Patreon, Supercast, etc.) through a simple UI.

### 2. **Sync All Sources**  
One-click sync that checks all your sources and downloads only new content.

### 3. **New Podcast Plugins**
- Invest Like the Best (transcripts + audio)
- MacroVoices (transcripts + audio)
- Peter Zeihan (audio)

## 🚀 Quick Start

### 1. Install New Dependencies

```bash
# Make sure you're in your virtual environment
source venv/bin/activate

# Install new packages
pip install feedparser yt-dlp
```

### 2. Start the App

```bash
python app.py
```

Open http://localhost:5002 in your browser.

### 3. Try the Private RSS Feed Feature

1. Click the **"Private RSS Feeds"** tab
2. Add a test feed (or your actual Sam Harris/Patreon feed):
   - **Feed Name**: Making Sense with Sam Harris
   - **RSS URL**: [Your private RSS URL]
   - **Author**: Sam Harris (optional)
3. Click **"Add Feed"**
4. It will validate the feed and save it to `.private/rss_feeds.json`

### 4. Index and Download Private Feed Content

1. Go back to the **"Content"** tab
2. Select **"Private RSS Feeds"** from the Site dropdown
3. Click **"Scan Content"** - you'll see all episodes from your private feeds
4. Select episodes and click **"Download Selected Content"**

### 5. Try the Sync Feature

1. Click the **"Sync All"** tab
2. Click **"Start Sync"**
3. It will:
   - Check all enabled sources (Lex Fridman, Conversations with Tyler, your private feeds, etc.)
   - Compare with what you've already downloaded
   - Download only NEW content
   - Show you a summary of what was downloaded
4. Check `downloads/sync_log.jsonl` for detailed logs

### 6. Try New Podcast Sources

Select from the dropdown:
- **Invest Like the Best** - Patrick O'Shaughnessy's podcast
- **MacroVoices** - Finance/macro podcast
- **Peter Zeihan** - Geopolitics podcast

## 📁 File Structure

```
crawlavator/
├── .private/                      # NEW: Private RSS feeds (gitignored)
│   ├── rss_feeds.json            # Your private feed URLs
│   └── README.md
├── sites/
│   ├── private_rss/              # NEW: Generic RSS plugin
│   ├── invest_like_best/         # NEW: Invest Like the Best plugin
│   ├── macrovoices/              # NEW: MacroVoices plugin
│   ├── peter_zeihan/             # NEW: Peter Zeihan plugin
│   ├── lexfridman/               # Existing
│   ├── conversationswithtyler/   # Existing
│   └── eurodollar/               # Existing
├── shared/
│   ├── sync_manager.py           # NEW: Sync logic
│   └── download_manager.py       # Existing
├── downloads/
│   └── sync_log.jsonl            # NEW: Sync operation logs
├── templates/
│   └── index.html                # UPDATED: New tabs
├── static/
│   ├── app.js                    # UPDATED: New features
│   └── style.css                 # UPDATED: New styles
├── app.py                        # UPDATED: New API routes
├── requirements.txt              # UPDATED: New dependencies
├── .gitignore                    # UPDATED: Excludes .private/
├── IMPLEMENTATION_STATUS.md      # NEW: Detailed status
└── GETTING_STARTED.md            # NEW: This file
```

## 🔐 Security Notes

- **Private RSS URLs are gitignored**: The `.private/` directory is excluded from git
- **Local storage only**: All private URLs stay on your machine
- **No sharing**: Private RSS URLs are unique to your subscription

## 🎯 Use Cases

### Use Case 1: Add Multiple Paid Podcasts

```
1. Get private RSS URLs from:
   - Sam Harris → samharris.org account page
   - Patreon podcasts → Patreon RSS feed setting
   - Supercast podcasts → Supercast dashboard

2. Add each one through the "Private RSS Feeds" tab

3. They all appear in the "Private RSS Feeds" source in the dropdown

4. Download individually or use "Sync All" to get everything
```

### Use Case 2: Daily Sync Routine

```
1. Open Crawlavator
2. Go to "Sync All" tab
3. Click "Start Sync"
4. Get coffee ☕
5. Come back to see what's new
6. Everything is organized in your downloads folder
```

### Use Case 3: Bulk Archive Setup

```
1. Add all your podcast sources (public + private)
2. Let each source index (may take a minute per source)
3. Select all content from one source
4. Download overnight
5. Use "Sync All" daily to stay current
```

## 🛠️ Adding More Podcast Sources

Want to add Ezra Klein, Odd Lots, or another podcast? Follow this pattern:

### Create Plugin File

`sites/your_podcast/__init__.py`:

```python
from .. import BaseSite, ContentItem, register_site
import feedparser

@register_site
class YourPodcastSite(BaseSite):
    SITE_ID = "your_podcast"
    SITE_NAME = "Your Podcast Name"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript", "audio"]
    CATEGORIES = ["podcast"]
    
    RSS_URL = "https://your-podcast-rss-url.com/feed"
    
    def index_content(self, progress_callback=None):
        # Parse RSS feed using feedparser
        # Return list of ContentItem objects
        pass
    
    def download_item(self, item, output_dir, progress_callback=None):
        # Download transcript or audio
        # Return (True, "Success message") or (False, "Error message")
        pass
```

### Import in app.py

```python
from sites.your_podcast import YourPodcastSite
```

See `sites/invest_like_best/__init__.py` for a complete example!

## 📊 Features by Source

| Source | Transcripts | Audio | Auth Required |
|--------|-------------|-------|---------------|
| Lex Fridman | ✅ | ✅ | No |
| Conversations with Tyler | ✅ | ✅ | No |
| Eurodollar University | ✅ | ✅ | Yes |
| Invest Like the Best | ✅ | ✅ | No |
| MacroVoices | ✅ | ✅ | No |
| Peter Zeihan | ❌ | ✅ | No |
| Private RSS Feeds | Varies | ✅ | Varies |

## 🐛 Troubleshooting

### "No episodes found" when indexing private feed
- Verify your RSS URL is correct
- Check that your subscription is active
- Try the URL in a podcast app first

### Sync shows "0 sources checked"
- Make sure you've indexed at least one source first
- Click "Scan Content" on each source you want to sync

### Can't find .private directory
- It's hidden (starts with a dot)
- Use `ls -la` in terminal or show hidden files in Finder
- It's created automatically when you add your first private feed

## 💡 Tips

1. **Start small**: Add 1-2 sources, test thoroughly, then expand
2. **Use Sync**: Much easier than manually checking each source
3. **Organize your feeds**: Use clear names in the Private RSS manager
4. **Check logs**: `downloads/sync_log.jsonl` shows sync history
5. **Regular syncs**: Run daily to stay current without bulk downloads

## 🎓 Next Steps

1. Add your paid podcast RSS feeds
2. Set up a daily sync routine
3. Create plugins for other podcasts you follow (see IMPLEMENTATION_STATUS.md)
4. Enjoy your organized podcast archive!

## 📚 Additional Resources

- **IMPLEMENTATION_STATUS.md** - Detailed implementation notes
- **README.md** - Original Eurodollar University features
- Plugin examples in `sites/` directories

---

**Questions?** Check the code comments or create an issue!

