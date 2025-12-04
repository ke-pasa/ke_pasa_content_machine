#!/bin/sh
set -eu

LOG_DIR=/var/log/app
mkdir -p "$LOG_DIR"
# ensure file exists for copytruncate to succeed
: > "$LOG_DIR/publisher_run.log"

# write cron job
CRON_FILE=/etc/cron.d/logrotate-app
echo "0 0 * * * root /usr/sbin/logrotate -s /var/lib/logrotate/status /etc/logrotate.d/ke-pasa" > "$CRON_FILE"
chmod 0644 "$CRON_FILE"
crontab "$CRON_FILE"

# run once on startup to trim oversized files
/usr/sbin/logrotate -s /var/lib/logrotate/status /etc/logrotate.d/ke-pasa || true

exec cron -f
