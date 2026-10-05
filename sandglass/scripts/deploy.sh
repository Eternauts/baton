#!/usr/bin/env bash
# One-command setup and deploy of Baton Sandglass on Google Cloud. Safe to re-run.
#
#   PROJECT_ID=my-project ./scripts/deploy.sh
#
# Options: REGION (default asia-southeast1), BUCKET (default <project>-baton-corpus),
#          MIN_INSTANCES (default 0; 1 removes cold starts), SKIP_TESTS=1.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-asia-southeast1}"
BUCKET="${BUCKET:-${PROJECT_ID}-baton-corpus}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
SERVICE="baton-sandglass"
SA_NAME="baton-sandglass"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"

step() { printf '\n==> %s\n' "$*"; }
gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  step "Tests"
  ( cd "$ROOT" && python3 -m venv .venv && . .venv/bin/activate \
      && pip install -q -r requirements-dev.txt && BATON_USE_EMBEDDINGS=false pytest -q )
fi

step "Enable APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com storage.googleapis.com secretmanager.googleapis.com iam.googleapis.com

step "Runtime service account (least privilege)"
if ! gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name="Baton Sandglass on Cloud Run"
  sleep 10
fi
for role in roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role="$role" \
    --condition=None --quiet >/dev/null
done
# Source deploys build with the default compute service account.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder" --condition=None --quiet >/dev/null

step "Artifact Registry repo for CI builds (cloudbuild.yaml)"
if ! gcloud artifacts repositories describe baton --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create baton --repository-format=docker --location="$REGION"
fi

step "Corpus bucket gs://$BUCKET"
if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access
fi
# The service reads the corpus and writes its index cache: scoped to this bucket only.
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
  --role=roles/storage.objectAdmin --quiet >/dev/null
# Upload the sample corpus only if the bucket has none yet; afterwards manage documents in the bucket.
if ! gcloud storage ls "gs://$BUCKET/corpus/" >/dev/null 2>&1; then
  gcloud storage cp "$ROOT"/corpus/* "gs://$BUCKET/corpus/"
fi

step "Secrets (device API key, admin key)"
for secret in baton-sandglass-api-keys baton-sandglass-admin-key; do
  if ! gcloud secrets describe "$secret" >/dev/null 2>&1; then
    key="$(openssl rand -hex 24)"
    printf '%s' "$key" | gcloud secrets create "$secret" --replication-policy=automatic --data-file=-
    echo "Created $secret. Value (shown once; also readable with 'gcloud secrets versions access latest --secret=$secret'):"
    echo "  $key"
  fi
  gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
done

step "Deploy $SERVICE to Cloud Run in $REGION (version $VERSION)"
# Auth is an application-level API key (devices cannot hold Google identities), so the service is public at
# the IAM layer. Concurrency stays moderate because each request waits on Gemini, not on local CPU.
gcloud run deploy "$SERVICE" \
  --region "$REGION" --source "$ROOT" --service-account "$SA" --allow-unauthenticated \
  --cpu 1 --memory 1Gi --concurrency 40 --timeout 60 \
  --min-instances "$MIN_INSTANCES" --max-instances 2 --cpu-boost \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,BATON_EMBED_LOCATION=${REGION},BATON_CORPUS_URI=gs://${BUCKET}/corpus,BATON_INDEX_URI=gs://${BUCKET}/index,BATON_VERSION=${VERSION}" \
  --set-secrets "BATON_API_KEYS=baton-sandglass-api-keys:latest,BATON_ADMIN_KEY=baton-sandglass-admin-key:latest" \
  --labels "app=baton,component=sandglass"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
KEY="$(gcloud secrets versions access latest --secret=baton-sandglass-api-keys)"

step "Smoke test"
curl -fsS "$URL/health"; echo
curl -fsS -H "X-API-Key: $KEY" "$URL/v1/corpus"; echo
curl -sS --compressed -H "X-API-Key: $KEY" -H "Content-Type: application/json" "$URL/v1/ask" \
  -d '{"q":"Can hot work continue on the stripper platform while GD-311 is bypassed?","budget":800}'; echo

cat <<MSG

Live at $URL
Add documents:  gcloud storage cp my-docs/* gs://$BUCKET/corpus/   (instances reload within BATON_REFRESH_S)
Force reindex:  curl -X POST -H "X-Admin-Key: \$(gcloud secrets versions access latest --secret=baton-sandglass-admin-key)" $URL/v1/admin/reindex
MSG
