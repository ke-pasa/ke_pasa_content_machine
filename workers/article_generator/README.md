# Article Generator Worker

Worker for automated article generation from RSS news.

## 📋 Description

Article Generator Worker processes Spanish news articles, translates them to Russian, and generates formatted content for publication. Saves articles to Firebase and optionally to local files.

## 🚀 Usage

### From project root:
```bash
python -m workers.article_generator.worker
```

### Direct execution:
```bash
cd workers/article_generator
python worker.py
```

### Via main.py:
```bash
python main.py generator
```

### Windows batch file:
```batch
run_generator.bat
```

## ⚙️ Configuration

Environment variables in `.env`:

```env
# Lock lease time (seconds)
GENERATOR_LOCK_LEASE_SEC=300

# Maximum articles per run
GENERATOR_BATCH_SIZE=50

# Folder for saving articles
GENERATOR_ARTICLES_DIR=articles

# Save articles to files
GENERATOR_SAVE_FILES=true

# Minimum text length for generation
GENERATOR_MIN_TEXT_LENGTH=50

# Use AI for enhancement
GENERATOR_USE_AI=true

# Generate article images and AI image prompts
ARTICLE_GENERATOR_ENABLE_IMAGES=false
```

## 🔒 Locking

Uses Firebase locks to prevent concurrent execution:
- Document: `locks/article_generator`
- Automatic stale lock cleanup
- Configurable lease time

## 📊 Output

```json
{
  "status": "success",
  "generated": 45,
  "total": 50,
  "errors": [],
  "instance_id": "abc123de",
  "timestamp": "2025-11-01T12:00:00Z"
}
```

## 🔄 Scheduling

Recommended: run every 10-15 minutes

**Windows Task Scheduler:**
```
Trigger: Repeat every 10 minutes
Action: python main.py generator
```

**Linux Cron:**
```cron
*/10 * * * * cd /path/to/project && python main.py generator
```

## 📁 Article Files

When `GENERATOR_SAVE_FILES=true`, articles are saved to:
```
articles/
├── article_id_1.txt
├── article_id_2.txt
└── ...
```

Each file contains:
- Original Spanish article
- Generated Russian article
- Metadata (priority, categories, etc.)

## 📝 Logs

All operations logged with `[article-generator]` prefix:
- ✅ Successful operations
- ❌ Errors
- ⚠️  Warnings
- 🔒 Lock status

## 🐛 Debugging

```python
from workers.article_generator import ArticleGeneratorWorker, GeneratorConfig

# Create custom configuration
config = GeneratorConfig(
    batch_size=10,
    save_to_files=True,
    articles_dir="test_articles"
)

# Run with debugging
worker = ArticleGeneratorWorker(config)
result = worker.generate_articles()
print(result)
```

## ⚡ Performance

- Processing 50 articles: 5-15 minutes (depending on AI API)
- AI-powered translation and enhancement
- Automatic validation of required fields
- Batch processing for efficiency
