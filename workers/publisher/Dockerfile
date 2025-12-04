FROM python:3.13

ENV PYTHONUNBUFFERED=1 \
    TELEGRAM_BOT_TOKEN="" \
    TELEGRAM_CHAT_ID="" \
    POSTGRES_URL="" \
    LIMIT="3"

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY workers/publisher/requirements.txt ./workers/publisher/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r workers/publisher/requirements.txt

COPY . .

ENTRYPOINT ["python", "-m", "workers.publisher.worker"]
CMD ["--limit", "3"]
