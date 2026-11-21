# SAP Change Impact & Regression Risk Agent - single-container image.
# Runs the FastAPI backend AND serves the static SPA from /frontend.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY simulator ./simulator
COPY scripts ./scripts
COPY evaluation ./evaluation
COPY tests ./tests

# SQLite by default; override DATABASE_URL for Postgres deployments.
RUN mkdir -p /app/data

EXPOSE 8013

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8013/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8013"]
