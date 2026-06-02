#!/bin/bash
# Azure App Service (Linux) startup script for the FastAPI backend.
# Set this as the Startup Command in Azure Portal:
#   Configuration → General settings → Startup Command → "bash startup.sh"

# Install dependencies
pip install -r requirements.txt

# Start uvicorn with multiple workers
# --timeout-keep-alive 65 ensures Azure's 230s idle timeout is handled gracefully.
# --timeout-graceful-shutdown 30 allows in-flight SSE streams to finish on deploy.
exec gunicorn api.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers 1 \
  --timeout 600 \
  --keep-alive 65 \
  --graceful-timeout 30 \
  --access-logfile -
gunicorn api.main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --timeout 600 --keep-alive 65 --graceful-timeout 30 --access-logfile -
