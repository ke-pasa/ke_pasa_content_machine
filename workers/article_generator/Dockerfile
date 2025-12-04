FROM python:3.13

ENV PYTHONUNBUFFERED=1 \
    OPENAI_API_KEY="" \
    POSTGRES_URL="" \
    ARTICLE_GENERATOR_FAIL_ON_ERRORS=""

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY workers/article_generator/requirements.txt ./workers/article_generator/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r workers/article_generator/requirements.txt

COPY . .

ENTRYPOINT ["python", "-m", "workers.article_generator.worker"]
CMD ["--batch-size", "20"]
