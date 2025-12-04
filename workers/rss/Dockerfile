FROM python:3.13

ENV PYTHONUNBUFFERED=1 \
    POSTGRES_URL="" \
    RSS_FEEDS_FILE="workers/rss/feeds.txt" \
    RSS_PARALLEL_FEEDS="6" \
    RSS_PURGE_DAYS="7"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2-dev libxslt-dev libpq-dev netcat-openbsd build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY workers/rss/requirements.txt ./workers/rss/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r workers/rss/requirements.txt

COPY . .

ENTRYPOINT ["python", "-m", "workers.rss.worker"]
