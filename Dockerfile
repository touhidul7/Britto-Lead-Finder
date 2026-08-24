FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install \
        --no-cache-dir \
        --prefer-binary \
        --timeout 120 \
        --retries 10 \
        -r requirements.txt

COPY . ./

RUN mkdir -p data exports credentials
