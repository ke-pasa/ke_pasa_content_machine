# ke_pasa_content_machine

## Docker Compose deployment

A `docker-compose.yml` is provided to run the Telegram publisher with persistent logging and monitoring:

- `publisher` pipes stdout/stderr to `logs/publisher_run.log` (mounted to the host) and also keeps a bounded Docker log via the `local` driver.
- `logrotate` trims `logs/*.log` daily (7 retained archives, compressed) so publisher logs do not grow unbounded.
- `exit-notifier` listens to Docker events and sends Telegram or email alerts when any container exits with a non-zero code (configure `TELEGRAM_*` or SMTP/`ALERT_EMAIL` variables).
- `node-exporter` exposes node metrics for Prometheus/Alertmanager or Oracle Cloud Monitoring.

Run the stack:

```bash
docker compose up -d --build
```

To view logs locally:

```bash
tail -f logs/publisher_run.log
```
