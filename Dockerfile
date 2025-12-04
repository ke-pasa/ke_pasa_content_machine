ARG SERVICE
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed for common Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install worker-specific dependencies
COPY workers/${SERVICE}/requirements.txt /tmp/worker-requirements.txt
RUN pip install --no-cache-dir -r /tmp/worker-requirements.txt

# Copy the codebase
COPY . /app

ENV PYTHONPATH=/app

CMD ["python", "-m", "workers.${SERVICE}.worker"]
