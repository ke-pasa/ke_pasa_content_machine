# Publisher Worker

Worker for automated article publication to Telegram channels.

## 📋 Description

Publisher Worker handles scheduled publication of generated articles to Telegram. Manages publication timing, retry logic, and ensures no duplicate publications.

## 🚀 Usage

### From project root:
```bash
python -m workers.publisher.worker
```

### Direct execution:
```bash
cd workers/publisher
python worker.py
```

### Via main.py:
```bash
python main.py publisher
```

### Windows batch file:
```batch
run_publisher.bat
```

## ⚙️ Configuration

Environment variables in `.env`:

```env
# Lock lease time (seconds)
PUBLISHER_LOCK_LEASE_SEC=300

# Maximum articles per run
PUBLISHER_MAX_ARTICLES=10

# Delay between publications (seconds)
PUBLISHER_DELAY_SEC=60

# Retry failed publications
PUBLISHER_RETRY_FAILED=true

# Maximum retry attempts
PUBLISHER_MAX_RETRIES=3
```

## 🔒 Locking

Uses Firebase locks to prevent concurrent execution:
- Document: `locks/publisher`
- Automatic stale lock cleanup
- Configurable lease time

## 📊 Output

```json
{
  "status": "success",
  "published": 5,
  "total_checked": 10,
  "errors": [],
  "instance_id": "abc123de",
  "timestamp": "2025-11-01T12:00:00Z"
}
```

## 🔄 Scheduling

Recommended: run every 1 hour

**Windows Task Scheduler:**
```
Trigger: Repeat every 1 hour
Action: python main.py publisher
```

**Linux Cron:**
```cron
0 * * * * cd /path/to/project && python main.py publisher
```

## 📝 Logs

All operations logged with `[publisher]` prefix:
- ✅ Successful operations
- ❌ Errors
- ⚠️  Warnings
- 🔒 Lock status

## 🐛 Debugging

```python
from workers.publisher import PublisherWorker, PublisherConfig

# Create custom configuration
config = PublisherConfig(
    max_articles_per_run=5,
    publication_delay=30
)

# Run with debugging
worker = PublisherWorker(config)
result = worker.publish_articles()
print(result)
```

## ⚡ Performance

- Publication of 10 articles: 5-10 minutes
- Respects publication windows
- Automatic retry on failures
- Rate limiting to avoid Telegram API limits
