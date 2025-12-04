# ke_pasa_content_machine

Utilities for processing RSS feeds and publishing content. Before running workers inside a VM or container, verify that required services are reachable:

- **Postgres**: ensure `POSTGRES_URL` (or `PG_*` variables) points to a reachable database. The health check will attempt `SELECT 1` on startup.
- **Outbound egress**: confirm the VM can reach your RSS sources and the Telegram Bot API (publisher).
- **Optional container healthcheck**: you can wire the health check into Docker `HEALTHCHECK` to catch issues quickly.

## Health check

Run a quick connectivity check that mirrors the CI guard:

```bash
python -m workers.tools.health_check
```

### Configuration
- `POSTGRES_URL`/`PG_*`/`DATABASE_URL` — database DSN (same as the workers use).
- `HEALTHCHECK_RSS_URL` — override RSS URL to probe (defaults to the first entry in `workers/rss/feeds.txt`).
- `TELEGRAM_BOT_TOKEN` — optional; if present the check calls `getMe`, otherwise it pings the public Telegram API base URL.
- `HEALTHCHECK_TIMEOUT` — request timeout in seconds (default: `5`).

The command prints JSON with `ok`, `skipped`, or `error` statuses and exits non‑zero when any check fails.
