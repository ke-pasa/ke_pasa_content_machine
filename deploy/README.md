# Deployment on a VM with Docker Compose

This directory contains everything needed to run the workers on a VM without GitHub Actions. The stack uses Docker + Compose, .env-based secrets (do **not** commit your real `.env`), and optional systemd timers or cron jobs that execute one-shot containers via `docker compose run --rm <service>`.

## Prerequisites
- Linux VM with sudo access.
- Docker Engine and the Compose plugin installed (Compose v2). On Debian/Ubuntu:
  ```bash
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  ```
- Optional: Docker/OCI secrets store. Compose also reads environment variables from `.env` in the project root, which stays uncommitted because of `.gitignore`.

## Prepare environment variables
1. Copy the template and fill in secrets:
   ```bash
   cp .env.example .env
   $EDITOR .env
   ```
   Keep `.env` out of version control. If you prefer Docker/OCI secrets, create files under `/run/secrets/*` and export them into `.env` (for example `OPENAI_API_KEY=$(cat /run/secrets/openai_api_key)`), or adapt `docker compose` invocations to inject `--env-file` that points to your secret material.

2. Build the image and pull dependencies:
   ```bash
   docker compose build
   ```

## Compose services
`docker-compose.yml` defines one image (`ke-pasa-content-machine:latest`) with task-oriented services:

- **rss** — parses feeds. Uses persistent volumes for RSS caches and feed lists.
- **categorization** — categorizes articles; accepts `--batch-size` for large nightly runs.
- **article-generator** — translates and enriches content, persisting generated files.
- **translator** — optional profile to run generator-only batches; enable with `--profile translator`.
- **publisher** — pushes content to Telegram.

All services share the `logs` volume. Caches and artifacts use named volumes (`rss-cache`, `rss-feeds`, `articles`) so containers can be ephemeral.

### One-off executions
Run on demand:
```bash
docker compose run --rm rss
docker compose run --rm categorization --batch-size 2000
docker compose run --rm article-generator
docker compose run --rm publisher
```

For long-running behavior you can set `restart: unless-stopped` on a service in `docker-compose.yml`, but the defaults keep containers short-lived for schedulers.

## Scheduling with systemd timers
Copy the unit + timer pairs from `deploy/systemd/` to `/etc/systemd/system/`, adjust `/opt/ke_pasa_content_machine` to your checkout path, then enable them:
```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rss-hourly.timer categorization-nightly.timer article-generator-daily.timer publisher-hourly.timer
```
Timers call `docker compose run --rm <service>` with the required arguments (categorization uses `--batch-size 2000`).

## Scheduling with cron (alternative)
Edit `deploy/cron/crontab.example` to point at your repo path and install it:
```bash
crontab deploy/cron/crontab.example
```

## Logs and caches
- Application logs: persisted in the `logs` volume.
- RSS cache files: stored in `rss-cache` volume and referenced via `RSS_ETAG_CACHE`/`RSS_LM_CACHE` envs.
- Generated articles: stored in `articles` volume.

Back up or rotate volumes using `docker volume` commands on the host if needed.
