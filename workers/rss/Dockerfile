# Dockerfile for RSS Worker
# Optimized for GitHub Actions and production

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy dependency files
COPY workers/rss/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create user for security
RUN groupadd -r rssworker && useradd -r -g rssworker rssworker

# Copy code
COPY workers/rss/ /app/workers/rss/
COPY firebase_client.py /app/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Switch to user
USER rssworker

# Check dependencies
RUN python workers/rss/check_dependencies.py

# Default command
CMD ["python", "-m", "workers.rss.worker"]

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"