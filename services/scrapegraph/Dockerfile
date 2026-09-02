FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app
COPY --chown=app:app src/ ./src/
USER app

EXPOSE 8081

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8081"]
