FROM python:3.13

ENV PYTHONUNBUFFERED=1 \
    POSTGRES_URL="" \
    OPENAI_API_KEY="" \
    CATEGORIZATION_PARALLELISM="4" \
    BATCH_SIZE="10"

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY workers/categorization/requirements.txt ./workers/categorization/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r workers/categorization/requirements.txt

COPY . .

ENTRYPOINT ["python", "-m", "workers.categorization.worker"]
CMD ["--action", "categorize"]
