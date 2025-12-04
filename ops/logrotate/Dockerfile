FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends logrotate cron && \
    rm -rf /var/lib/apt/lists/*

COPY logrotate.conf /etc/logrotate.d/ke-pasa
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
