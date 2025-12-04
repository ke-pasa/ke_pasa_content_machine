FROM python:3.11-slim

RUN pip install --no-cache-dir docker requests

WORKDIR /app
COPY exit_notifier.py /app/exit_notifier.py

CMD ["python", "/app/exit_notifier.py"]
