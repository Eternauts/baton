FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The bundled corpus is the default; production points BATON_CORPUS_URI at a GCS prefix.
COPY app ./app
COPY corpus ./corpus

RUN useradd --uid 10001 --no-create-home sandglass
USER sandglass

# Cloud Run injects PORT.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --no-access-log
