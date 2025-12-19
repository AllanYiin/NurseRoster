FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BACKEND_HOST=0.0.0.0 \
    DATA_DIR=/data \
    LOG_DIR=/data/logs \
    EXPORT_DIR=/data/exports \
    DB_PATH=/data/app.db

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY start_backend.py /app/start_backend.py
COPY .env.example /app/.env.example

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('BACKEND_PORT') or os.getenv('APP_PORT') or os.getenv('PORT') or '8000'; urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health')" || exit 1

CMD ["python", "start_backend.py"]
