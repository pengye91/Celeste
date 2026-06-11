# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build deps first for packages with compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install production dependencies
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir "."

# Cleanup build deps
RUN apt-get purge -y --auto-remove gcc

EXPOSE 8000

# Default: run the FastAPI app via uvicorn
CMD ["uvicorn", "celeste.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
