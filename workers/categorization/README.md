# Categorization Worker

Worker for article prioritization and urgent news detection.

## 📋 Description

Categorization Worker analyzes articles and assigns priority scores based on relevance, timeliness, and importance. It also detects urgent news requiring immediate publication.

## 🚀 Usage

### From project root:
```bash
python -m workers.categorization.worker
```

### Direct execution:
```bash
cd workers/categorization
python worker.py
```

### Via main.py:
```bash
python main.py categorization
```

### Windows batch file:
```batch
run_categorization.bat
```

## ⚙️ Configuration

Environment variables in `.env`:

```env
# Lock lease time (seconds)
CATEGORIZATION_LOCK_LEASE_SEC=600

# Batch size for processing
CATEGORIZATION_BATCH_SIZE=100

# Enable urgent news detection
CATEGORIZATION_DETECT_URGENT=true

# Minimum priority score for urgent marking
CATEGORIZATION_URGENT_THRESHOLD=8.0

# Update all articles or only new ones
CATEGORIZATION_UPDATE_ALL=false
```

## 🎯 Priority Scores

- **8-10**: High priority (urgent news)
- **5-7**: Medium priority (important news)
- **0-4**: Low priority (regular news)

## 🔒 Locking

Uses Firebase locks to prevent concurrent execution:
- Document: `locks/categorization`
- Automatic stale lock cleanup
- Configurable lease time (default: 10 minutes)

## 📊 Output

```json
{
  "status": "success",
  "updated": 150,
  "urgent": 12,
  "errors": [],
  "instance_id": "abc123de",
  "timestamp": "2025-11-01T12:00:00Z"
}
```

## 🔄 Scheduling

Recommended: once per day (off-peak hours)

**Windows Task Scheduler:**
```
Trigger: Daily at 02:00
Action: python main.py categorization
```

**Linux Cron:**
```cron
0 2 * * * cd /path/to/project && python main.py categorization
```

## 📝 Logs

All operations logged with `[categorization]` prefix:
- ✅ Successful operations
- ❌ Errors
- ⚠️  Warnings
- 🔒 Lock status

## 🐛 Debugging

```python
from workers.categorization import CategorizationWorker, CategorizationConfig

# Create custom configuration
config = CategorizationConfig(
    batch_size=50,
    urgent_threshold=7.5,
    detect_urgent=True
)

# Run with debugging
worker = CategorizationWorker(config)
result = worker.update_priorities()
print(result)

# Get statistics
stats = worker.get_statistics()
print(stats)
```

## ⚡ Performance

- Processing 150 articles: 2-5 minutes
- AI-powered priority scoring
- Automatic urgent news detection
- Category assignment and validation
