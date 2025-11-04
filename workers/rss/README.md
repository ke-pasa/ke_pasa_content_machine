# RSS Worker

Worker for automated RSS feed parsing from news sources with automatic feed validation and cleanup.

## 📋 Description

RSS Worker reads RSS feeds from `feeds.txt`, validates each feed, and loads news into Firebase. 

**Key features:**
- 🔍 **Automatic feed validation**: checks if feeds are working
- 📅 **Freshness check**: removes feeds without articles < 30 days old
- 🧹 **Auto-cleanup**: maintains clean `feeds.txt` with only valid feeds
- 📝 **Problem tracking**: saves non-working and outdated feeds to separate files
- 🎯 **Content extraction**: extracts full text from articles (AI filtering currently disabled)
- 🔄 **Deduplication**: checks for duplicates by link, title hash, and content
- 📰 **Full-text extraction**: gets complete article content from source websites

## � Installation

**Current version (without OpenAI - LLM filtering disabled):**
```bash
pip install -r workers/rss/requirements.txt
```

**With OpenAI support (if needed for future LLM filtering):**
```bash
pip install -r workers/rss/requirements-with-openai.txt
```

## �🚀 Usage

### From project root:
```bash
python -m workers.rss.worker
```

### Direct execution:
```bash
cd workers/rss
python worker.py
```

### Via main.py:
```bash
python main.py rss
```

### Windows batch file:
```batch
run_rss.bat
```

## 🛠️ Feed Management Tool

Interactive utility for manual feed management:

```bash
python workers/rss/manage_feeds.py
```

**Features:**
- 📊 View statistics (working/broken/outdated feeds)
- 📋 List feeds by category
- 🔄 Restore feeds from problem lists back to main list
- ➕ Add new feeds manually
- 🗑️ Remove feeds manually

## ⚙️ Configuration

Environment variables in `.env`:

```env
# Path to RSS feeds file
RSS_FEEDS_FILE=workers/rss/feeds.txt

# Lock lease time (seconds)
RSS_LOCK_LEASE_SEC=300

# Max articles per run (0 = unlimited)
RSS_MAX_ARTICLES=0

# Request timeout (seconds)
RSS_REQUEST_TIMEOUT=30

# Retry attempts on error
RSS_RETRY_ATTEMPTS=3

# Delay between retries (seconds)
RSS_RETRY_DELAY=5
```

## 📁 Feeds File

Format of `feeds.txt`:
```
# RSS feeds - Automatically cleaned
# Updated: 2025-01-15 14:30:00
#

https://elpais.com/rss/elpais/portada.xml
https://www.elmundo.es/rss/portada.xml
# Comment lines start with #
https://www.abc.es/rss/feeds/abc_portada.xml
```

**Note:** The worker automatically updates this file, keeping only working feeds with recent articles.

## 🧹 Output Files

1. **`feeds.txt`**: Automatically updated with only valid feeds
2. **`feeds_not_working.txt`**: Feeds that don't open (HTTP errors, timeouts, parsing errors)
3. **`feeds_outdated.txt`**: Feeds without articles younger than 30 days

## 🔍 Feed Validation Logic

For each feed in `feeds.txt`:

1. ✅ **Connection check**: Attempts to parse feed with `feedparser`
2. 📅 **Freshness check**: Looks for articles published within last 30 days
3. 📝 **Result**:
   - **Valid**: Keep in `feeds.txt` and process articles
   - **Not working**: Move to `feeds_not_working.txt`
   - **Outdated**: Move to `feeds_outdated.txt`

## 🔒 Locking

Worker uses Firebase locks to prevent concurrent execution:
- Document: `locks/rss_worker`
- Automatic stale lock cleanup (>15 minutes)
- Configurable lease time

## 📊 Output

```json
{
  "status": "success",
  "message": "RSS feeds processed successfully",
  "instance_id": "abc123de",
  "feeds_file": "workers/rss/feeds.txt",
  "valid_feeds": 73,
  "not_working_feeds": 1,
  "outdated_feeds": 1,
  "timestamp": "2025-01-15T14:30:00Z"
}
```

## 📝 Example Console Output

```
[rss-worker] 🚀 Processing feeds from: workers/rss/feeds.txt
[rss-worker] 📋 Found 75 feeds to check
[rss-worker] 🔍 [1/75] Checking: https://elpais.com/rss/elpais/portada.xml
[rss-worker] ✅ Feed valid: 20 articles
[rss-worker] 🔍 [2/75] Checking: https://www.example.com/rss
[rss-worker] ❌ Feed not working: https://www.example.com/rss
[rss-worker] 🔍 [3/75] Checking: https://www.old-news.com/rss
[rss-worker] 📅 Feed outdated (no articles < 30 days): https://www.old-news.com/rss
[rss-worker] 📝 Updating feeds.txt: 73/75 valid
[rss-worker] 💾 Saved 1 not working feeds
[rss-worker] 💾 Saved 1 outdated feeds
[rss-worker] 🚀 Processing 73 valid feeds...
[rss-worker] ✅ Processing completed successfully
```

## 🔄 Scheduling

Recommended: run every 2 hours via cron or Task Scheduler

**Windows Task Scheduler:**
```
Trigger: Repeat every 2 hours
Action: python -m workers.rss.worker
```

**Linux Cron:**
```cron
0 */2 * * * cd /path/to/project && python -m workers.rss.worker
```

## 🐛 Debugging

```python
from workers.rss import RSSWorker, RSSConfig

# Create custom configuration
config = RSSConfig(
    feeds_file="test_feeds.txt",
    lock_lease_sec=60,
    max_articles_per_run=10
)

# Run with debugging
worker = RSSWorker(config)
result = worker.process_feeds()
print(result)

# Check status
status = worker.get_status()
print(status)
```

## ⚡ Performance

- Processing ~100 feeds: 5-10 minutes (validation + parsing)
- Feed validation: ~1-2 seconds per feed
- Parallel content loading where possible
- Automatic retry on errors
- Caching of processed articles in Firebase

## 🚀 GitHub Actions

### CI/CD Setup

1. **Dependencies optimized** for GitHub Actions in `requirements.txt`
2. **Workflow file**: `.github/workflows/rss-worker.yml`
3. **Secrets**: add in GitHub Settings > Secrets and variables > Actions:
   - `FIREBASE_PROJECT_ID` 
   - `FIREBASE_PRIVATE_KEY`
   - `FIREBASE_CLIENT_EMAIL`
   <!-- - `OPENAI_API_KEY` (not needed - LLM filtering disabled) -->

### CI Features:
- Runs every 2 hours on schedule
- Testing on Python 3.9, 3.10, 3.11
- Increased lock lease time (30 min)
- Limited items per feed (10)
- Automatic logs and artifacts saving

### Local testing:
```bash
# Use variables from .env.github-actions
cp workers/rss/.env.github-actions .env
# Edit secrets
nano .env
# Run
cd workers/rss && python -m worker
```

### System requirements (Ubuntu):
```bash
sudo apt-get update
sudo apt-get install -y libxml2-dev libxslt-dev
```
