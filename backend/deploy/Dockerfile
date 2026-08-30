# Vigilux Sentinel - Cloud Run image
# Build context: repo root (e.g.  gcloud builds submit --config backend/deploy/Dockerfile .)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching.
COPY backend/agents/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code (agents package). Data seed script is optional at runtime.
COPY backend/agents/ ./agents/
COPY backend/data/ ./data/

EXPOSE 8080
CMD ["uvicorn", "agents.main:app", "--host", "0.0.0.0", "--port", "8080"]