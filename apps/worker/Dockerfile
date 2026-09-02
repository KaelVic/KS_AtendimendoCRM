FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

COPY apps/worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/var \
    && chown -R app:app /app

COPY --chown=app:app apps/worker/src/ ./src/
COPY --chown=app:app apps/api/src/ ./api_src/
USER app

CMD ["python", "-m", "src.worker"]
