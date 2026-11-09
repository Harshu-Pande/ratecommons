# Dockerfile for the Hugging Face Space (Harshu-Pande/ratecommons-api). It builds the query server, and the website,
# from github.com/Harshu-Pande/ratecommons at RC_CODE_REF (a Space variable: Docker Spaces pass variables as build
# args). To release: set RC_CODE_REF to the commit and restart the Space with "Factory rebuild".
FROM node:22-slim AS site
ARG RC_CODE_REF=main
WORKDIR /src
ADD https://codeload.github.com/Harshu-Pande/ratecommons/tar.gz/${RC_CODE_REF} /tmp/src.tgz
RUN tar xzf /tmp/src.tgz --strip-components=1 && cd carecompass && npm ci --no-audit --no-fund && npm run build

FROM python:3.12-slim
ARG RC_CODE_REF=main
RUN useradd -m -u 1000 user
ENV HOME=/home/user PYTHONUNBUFFERED=1 \
    RC_WARM=1 RC_SITE_DIR=/app/site \
    RC_CACHE=/home/user/cache RC_CACHE_GB=30 RC_FILE_MB=4000 \
    RC_SCRATCH=/home/user/scratch RC_TEMP_MAX=8GB RC_SQL_TEMP_MAX=6GB \
    RC_MEMORY=9GB RC_SQL_MEMORY=5GB RC_SLICE_ROWS=20000000 RC_WIDE_ROWS_MAX=150000000 \
    RC_THREADS=2 RC_CONCURRENCY=3 RC_SQL_SECONDS=240 PORT=7860
WORKDIR /app
COPY --from=site /src/cloud/api /app/api
COPY --from=site /src/cloud/server/main.py /src/cloud/server/requirements.txt /app/
COPY --from=site /src/carecompass/dist /app/site
RUN pip install --no-cache-dir -r /app/requirements.txt && echo "${RC_CODE_REF}" > /app/REF
USER user
RUN mkdir -p /home/user/cache /home/user/scratch
EXPOSE 7860
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
