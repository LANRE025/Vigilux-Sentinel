#!/usr/bin/env bash
# Deploys Vigilux Sentinel to Cloud Run.
#
# Prereqs: gcloud authenticated + a project with Firestore and (for Gemini via
# Vertex AI) the Model Garden / Vertex AI enabled. The Cloud Run service uses
# the default Cloud Run runtime service account for Vertex AI / Firestore /
# Cloud Trace, so no API key is required.
#
#   export GOOGLE_CLOUD_PROJECT=my-project
#   export CLOUD_RUN_REGION=us-central1     # Google Cloud regional services location
#   ./deploy/cloudrun_deploy.sh
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${CLOUD_RUN_REGION:-us-central1}"
IMAGE="gcr.io/${PROJECT_ID}/vigilux-sentinel"
SERVICE="vigilux-sentinel"

# 1. Build and push the image (Dockerfile lives under backend/deploy).
gcloud builds submit --tag "${IMAGE}" --config backend/deploy/Dockerfile .

# 2. Ensure Firestore exists in the region (idempotent).
gcloud firestore databases create --location="${REGION}" --project="${PROJECT_ID}" || true

# 3. Deploy to Cloud Run. Gemini is reached through Vertex AI (global
#    location); the service authenticates via the runtime service account.
#    GEMINI_MODEL:          override the default model id.
#    MEMORY_BANK_AGENT_ENGINE_ID: enable the real Vertex AI Agent Engine.
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --cpu=1 \
  --memory=512Mi \
  --min-instances=0 \
  --concurrency=20 \
  --timeout=300 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},FIRESTORE_REGION=${REGION},FIRESTORE_DATABASE=,GEMINI_VERTEX_LOCATION=global,SURVEY_STALENESS_THRESHOLD_DAYS=30"

echo "Deployed. Find the service URL with:"
echo "  gcloud run services describe ${SERVICE} --region=${REGION} --format='value(status.url)'"
echo "Then seed the region data with (from the backend/ directory):"
echo "  python -m data.seed_regions"