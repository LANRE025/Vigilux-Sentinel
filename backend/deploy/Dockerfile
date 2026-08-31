# Vigilux Sentinel - Cloud Run image
# Build context: repo root (e.g.  gcloud builds submit --config backend/deploy/Dockerfile .)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching (runtime deps only - not the
# dev/test requirements, which the minimal runtime image does not need).
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code (agents package + top-level app module). Data seed script is optional at runtime.
COPY backend/agents/ ./agents/
COPY backend/main.py ./main.py
COPY backend/data/ ./data/

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]