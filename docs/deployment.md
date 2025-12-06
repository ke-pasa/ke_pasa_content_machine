# Docker Deployment Guide

This guide explains how to deploy the 4 workers (RSS, Categorization, Article Generator, Publisher) using Docker and GitHub Actions.

## Prerequisites

### Server Requirements

- **Operating System**: Ubuntu 20.04+ or Debian 11+
- **RAM**: Minimum 2GB (recommended 4GB)
- **Disk Space**: 10GB free
- **Docker**: Version 20.10+
- **Docker Compose**: Version 2.0+

### Install Docker on Server

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose (if not included)
sudo apt-get update
sudo apt-get install docker-compose-plugin

# Add your user to docker group
sudo usermod -aG docker $USER

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Verify installation
docker --version
docker compose version
```

**Note**: After adding user to docker group, log out and log back in for changes to take effect.

## GitHub Secrets Configuration

Add the following secrets in your GitHub repository (**Settings** → **Secrets and variables** → **Actions** → **New repository secret**):

### Required Secrets

| Secret Name | Description | Example |
|------------|-------------|---------|
| `DEPLOY_SERVER_HOST` | Server IP or hostname | `192.168.1.100` or `server.example.com` |
| `DEPLOY_SERVER_USER` | SSH username | `ubuntu` or `deploy` |
| `DEPLOY_SSH_KEY` | Private SSH key for server access | Your SSH private key content |
| `POSTGRES_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | `123456789:ABC...` |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID | `-1001234567890` |

### Optional Secrets

| Secret Name | Description | Default |
|------------|-------------|---------|
| `DEPLOY_SERVER_PORT` | SSH port | `22` |
| `RSS_PARALLEL_FEEDS` | Number of parallel RSS feeds | `6` |
| `RSS_PURGE_DAYS` | Days to keep old articles | `7` |

### Setup SSH Key

Generate SSH key pair if you don't have one:

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/deploy_key

# Copy public key to server
ssh-copy-id -i ~/.ssh/deploy_key.pub user@server-ip

# Test connection
ssh -i ~/.ssh/deploy_key user@server-ip

# Copy private key content for GitHub secret
cat ~/.ssh/deploy_key
# Copy the entire output including -----BEGIN and -----END lines
```

Add the private key content to `DEPLOY_SSH_KEY` secret in GitHub.

## Deployment Methods

### Method 1: Automatic Deployment (GitHub Actions)

The workflow is triggered automatically on push to `main` branch, or manually via GitHub Actions UI.

**Automatic on Push:**
```bash
git add .
git commit -m "Deploy workers"
git push origin main
```

**Manual Trigger:**
1. Go to **Actions** tab in GitHub
2. Select **Deploy Workers to Server** workflow
3. Click **Run workflow** → **Run workflow**

**What happens during deployment:**
1. ✅ Code checkout
2. ✅ Build Docker images (base + 4 workers)
3. ✅ Save images as tar archives
4. ✅ Transfer files to server via SCP
5. ✅ Load images on server
6. ✅ Stop old containers
7. ✅ Start new containers
8. ✅ Verify deployment

### Method 2: Manual Deployment on Server

If you prefer to deploy manually or for testing:

```bash
# SSH to server
ssh user@server-ip

# Clone repository
cd ~
git clone https://github.com/your-username/ke_pasa_content_machine.git
cd ke_pasa_content_machine

# Create .env file
cp .env.example .env
nano .env  # Edit and add your credentials

# Build and start containers
docker compose build
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

## Worker Schedules

Each worker runs on a specific schedule managed by Supervisor:

| Worker | Schedule | Frequency |
|--------|----------|-----------|
| RSS Worker | Every 8 hours | Fetches new articles from RSS feeds |
| Categorization Worker | Every 2 hours | Categorizes new articles |
| Article Generator Worker | Every 30 minutes | Generates translated articles |
| Publisher Worker | Every 1 hour | Publishes articles to Telegram |

## Managing Containers

### View Running Containers

```bash
# SSH to server
ssh user@server-ip
cd ~/ke-pasa-workers

# List all containers
docker compose ps

# View specific worker logs
docker compose logs rss-worker
docker compose logs categorization-worker
docker compose logs article-generator-worker
docker compose logs publisher-worker

# Follow logs in real-time
docker compose logs -f rss-worker
```

### Restart Workers

```bash
# Restart all workers
docker compose restart

# Restart specific worker
docker compose restart rss-worker
docker compose restart categorization-worker
docker compose restart article-generator-worker
docker compose restart publisher-worker
```

### Stop Workers

```bash
# Stop all workers
docker compose down

# Stop specific worker
docker compose stop rss-worker
```

### Update Workers

After code changes:

```bash
# GitHub Actions will automatically deploy on push to main
# OR manually rebuild and restart:
docker compose down
docker compose build --no-cache
docker compose up -d
```

## Monitoring

### Check Worker Status

```bash
# From server
docker compose ps

# Expected output:
# NAME                              STATUS
# ke-pasa-rss-worker               Up X minutes
# ke-pasa-categorization-worker    Up X minutes
# ke-pasa-article-generator-worker Up X minutes
# ke-pasa-publisher-worker         Up X minutes
```

### View Logs

Logs are stored in `~/ke-pasa-workers/logs/` directory:

```bash
# View all logs
docker compose logs

# View recent logs (last 100 lines)
docker compose logs --tail=100

# View logs for specific worker
docker compose logs --tail=50 rss-worker

# Follow logs in real-time
docker compose logs -f article-generator-worker

# View logs from specific time
docker compose logs --since="2024-01-01T10:00:00"
```

### Supervisor Status

Check supervisor process status inside container:

```bash
# Access container shell
docker exec -it ke-pasa-rss-worker bash

# Check supervisor status
supervisorctl status

# Restart process
supervisorctl restart rss-worker

# Exit container
exit
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs worker-name

# Check if image exists
docker images | grep ke-pasa

# Rebuild image
docker compose build --no-cache worker-name
docker compose up -d
```

### Worker Crashes Immediately

```bash
# Check environment variables
docker compose config

# Check worker logs
docker compose logs --tail=200 worker-name

# Verify .env file
cat .env
```

### SSH Connection Issues

```bash
# Test SSH connection
ssh -i ~/.ssh/deploy_key -v user@server-ip

# Check SSH key permissions
chmod 600 ~/.ssh/deploy_key

# Verify public key on server
cat ~/.ssh/authorized_keys
```

### Database Connection Issues

```bash
# Verify POSTGRES_URL format
# Should be: postgresql://user:password@host:port/database

# Test connection from container
docker exec -it ke-pasa-rss-worker bash
python -c "import psycopg2; conn = psycopg2.connect('$POSTGRES_URL'); print('Connected!')"
```

### Out of Memory

```bash
# Check memory usage
free -h

# Check Docker memory usage
docker stats

# Add more RAM or reduce worker frequency
```

## Cleanup

### Remove Old Images

```bash
# Remove unused images
docker image prune -f

# Remove all unused containers, networks, images
docker system prune -a -f
```

### Remove All Workers

```bash
cd ~/ke-pasa-workers
docker compose down
docker rmi $(docker images 'ke-pasa-*' -q)
```

## Security Best Practices

1. **Never commit** `.env` file to git
2. **Use GitHub Secrets** for sensitive data
3. **Rotate SSH keys** periodically
4. **Keep Docker updated** on server
5. **Use firewall** to restrict server access
6. **Monitor logs** for suspicious activity

## Support

For issues or questions:

1. Check logs: `docker compose logs`
2. Review this documentation
3. Check GitHub Actions workflow logs
4. Verify all secrets are set correctly in GitHub

## Architecture Overview

```
GitHub Repository (main branch push)
         ↓
GitHub Actions Workflow
         ↓
Build Docker Images (base + 4 workers)
         ↓
Transfer to Server via SSH/SCP
         ↓
Server: Load & Deploy Containers
         ↓
4 Workers Running with Supervisor
         ↓
Continuous Execution on Schedule
```

Each worker runs independently in its own container with Supervisor managing the execution loop and automatic restarts on failures.
