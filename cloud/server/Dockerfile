# RateCommons query server: the same app as the Vercel function (cloud/api), run as one persistent process with a
# large local cache and enough memory to answer big questions in one pass. Runs on any container host; first home is
# a Hugging Face Docker Space (port 7860, user 1000). Built from the repo root: docker build -f cloud/server/Dockerfile .
FROM python:3.12-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user PYTHONUNBUFFERED=1 \
    RC_WARM=1 \
    RC_CACHE=/home/user/cache RC_CACHE_GB=30 RC_FILE_MB=4000 \
    RC_SCRATCH=/home/user/scratch RC_TEMP_MAX=8GB RC_SQL_TEMP_MAX=6GB \
    RC_MEMORY=9GB RC_SQL_MEMORY=5GB RC_SLICE_ROWS=20000000 RC_WIDE_ROWS_MAX=150000000 \
    RC_THREADS=2 RC_CONCURRENCY=3 RC_SQL_SECONDS=240 PORT=7860

WORKDIR /app
COPY cloud/server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY cloud/api/ /app/api/
COPY cloud/server/main.py /app/main.py

USER user
RUN mkdir -p /home/user/cache /home/user/scratch
EXPOSE 7860
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
