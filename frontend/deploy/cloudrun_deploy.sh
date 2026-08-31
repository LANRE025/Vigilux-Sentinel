#!/usr/bin/env bash
# Deploys Vigilux Sentinel Frontend to Cloud Run.
#
# Mirrors the backend deploy script pattern:
#   Build context: repo root
#   Dockerfile:    frontend/deploy/Dockerfile
#   Image:         gcr.io/$PROJECT_ID/vigilux-sentinel-frontend
#   Service:       vigilux-sentinel-frontend
#
# Prereqs: gcloud authenticated + a project with Cloud Run enabled.
#
#   export GOOGLE_CLOUD_PROJECT=my-project
#   export CLOUD_RUN_REGION=us-central1
#   export BACKEND_URL=https://vigilux-sentinel-xxxx-uc.a.run.app
#   ./frontend/deploy/cloudrun_deploy.sh
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${CLOUD_RUN_REGION:-us-central1}"
BACKEND_URL="${BACKEND_URL:?Set BACKEND_URL to the deployed backend URL}"
IMAGE="gcr.io/${PROJECT_ID}/vigilux-sentinel-frontend"
SERVICE="vigilux-sentinel-frontend"

# 1. Build and push the image (Dockerfile lives under frontend/deploy).
gcloud builds submit \
  --tag "${IMAGE}" \
  --config frontend/deploy/Dockerfile \
  --build-arg "VITE_API_URL=${BACKEND_URL}" \
  --build-arg "VITE_DEMO=false" \
  .

# 2. Deploy to Cloud Run.
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --cpu=1 \
  --memory=256Mi \
  --min-instances=0 \
  --concurrency=80 \
  --timeout=60

echo "Deployed. Find the service URL with:"
echo "  gcloud run services describe ${SERVICE} --region=${REGION} --format='value(status.url)'"
