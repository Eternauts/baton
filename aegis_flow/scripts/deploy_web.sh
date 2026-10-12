#!/usr/bin/env bash
# Build the Baton app for the browser and deploy it as its own Cloud Run service (baton-app).
# The API and the supervisor dashboard are a different service (baton-api, backend/scripts/deploy.sh).
#   scripts/deploy_web.sh           -> build + deploy baton-app (serves 100% immediately: it is a static site)
# Needs: flutter, gcloud, and the demo key (backend/scripts/setup_web.sh creates it once).
set -euo pipefail

PROJECT="${PROJECT:-ai-builder-cup-2026-509818}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-baton-app}"
API_URL="${API_URL:-https://baton-api-545013329202.asia-southeast1.run.app}"
cd "$(dirname "$0")/.."

command -v flutter >/dev/null || { echo "flutter is not on PATH" >&2; exit 1; }
# The page ships this key to every visitor, so it is the DEMO key: it opens the app endpoints only, never the supervisor ones.
DEMO_KEY="$(gcloud secrets versions access latest --secret=aegis-demo-key --project "$PROJECT")" \
  || { echo "Create the demo key first: backend/scripts/setup_web.sh" >&2; exit 1; }

flutter build web --release --pwa-strategy=none --no-wasm-dry-run --no-web-resources-cdn \
  --dart-define=AEGIS_API_KEY="$DEMO_KEY" --dart-define=BACKEND_URL="$API_URL"

STAGE="build/web_image"
rm -rf "$STAGE" && mkdir -p "$STAGE" && cp web_hosting/Dockerfile web_hosting/nginx.conf "$STAGE/" && cp -R build/web "$STAGE/site"
echo "site staged: $(du -sh "$STAGE/site" | cut -f1)"

CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source "$STAGE" \
  --allow-unauthenticated --port 8080 --cpu 1 --memory 256Mi --min-instances 0 --max-instances 3
echo "Baton app: $(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
