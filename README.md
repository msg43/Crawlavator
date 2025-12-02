# Crawlavator

A local web application to batch download your content from [Eurodollar University](https://www.eurodollar.university).

## Features

- 📋 **Index all your content** - Scans videos, articles, PDFs, audio files, and transcripts
- 🔍 **Search and filter** - Find content by name, category, or type
- ☑️ **Batch select** - Select All / Select None with category filters
- 🎥 **Download videos** - Extracts HLS streams using ffmpeg
- 📝 **Download DDA articles** - Saves HTML with embedded images
- 📄 **Download PDFs** - Daily Briefings and slides
- 🎧 **Download audio** - M4A/MP3 files for offline listening
- 📋 **Download transcripts** - Text versions of video content
- 📁 **Organized folder structure** - Content organized by category
- ⏱️ **Resume capability** - Tracks downloads, skips completed files
- 🔄 **Graceful error handling** - Logs restricted content, continues on errors

## Prerequisites

- Python 3.10 or higher
- An active Eurodollar University subscription
- **ffmpeg** (required for video downloads)

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (with Chocolatey)
choco install ffmpeg
```

## Installation

1. **Clone the repository**
```bash
git clone https://github.com/msg43/crawlavator.git
cd crawlavator
```

2. **Create a virtual environment** (recommended)
```bash
python -m venv venv
source venv/bin/activate  # On macOS/Linux
# or
.\venv\Scripts\activate   # On Windows
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Install Playwright browsers**
```bash
playwright install chromium
```

## Usage

1. **Start the application**
```bash
python app.py
```

2. **Open your browser** and go to http://localhost:5000

3. **Configure your credentials**
   - Enter your email and password
   - Click "Save Configuration"
   - Click "Login" or use "Open Browser for Manual Login"

4. **Scan content** by clicking "Scan Content"

5. **Filter and select** content using:
   - Category checkboxes (Membership, DDA, Daily Briefing)
   - Search box
   - Select All / Select None buttons

6. **Choose download options** (Videos, Articles, PDFs, Audio, Transcripts)

7. **Click "Download Selected Content"** and wait for completion

## Download Folder Structure

```
downloads/
├── manifest.json              # Tracks all downloads
├── access_log.json            # Logs restricted/error content
├── membership/
│   ├── the-basics/
│   │   └── Basics_14_IR_Swap_Spreads/
│   │       └── video.mp4
│   ├── classroom/
│   ├── qna/
│   ├── audio/
│   │   └── QnA178_2025-11-18.m4a
│   └── transcripts/
├── dda/
│   └── Article_Title/
│       ├── article.html
│       └── images/
├── daily-briefing/
│   └── 2025-12-01_ISM_M.pdf
```

## Configuration

Configuration is stored in `config.json` (automatically created, gitignored):

```json
{
  "email": "your@email.com",
  "password": "your-password",
  "download_dir": "~/Downloads/eurodollar"
}
```

Browser session is stored in `.browser_session/` (also gitignored).

## Intelligent Resume

The downloader tracks all downloads in `manifest.json`:
- Skips already-completed downloads
- Resumes partial downloads
- Logs restricted content without stopping
- Supports "download new only" for incremental updates

## Troubleshooting

### "Authentication required" error
- Make sure your email and password are correct
- Try "Open Browser for Manual Login" for interactive login

### Video download fails
- Ensure ffmpeg is installed and in your PATH
- Check that your subscription includes video access

### Some content shows as "restricted"
- This content requires a subscription tier you don't have
- Restricted items are logged but don't stop the download process

## Security Notes

- All credentials are stored locally in `config.json`
- Browser session is stored locally in `.browser_session/`
- No data is sent to any third-party servers
- The config and session files are gitignored by default

## License

MIT License - see LICENSE for details.

## Disclaimer

This tool is not affiliated with or endorsed by Eurodollar University or Jeff Snider. Use responsibly and in accordance with the site's Terms of Service.

