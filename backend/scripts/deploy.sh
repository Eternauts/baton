#!/usr/bin/env bash
# Deploy baton-api to Cloud Run from source.
#   scripts/deploy.sh canary    -> new revision, 0% traffic, reachable at https://canary---<service-url>
#   scripts/deploy.sh promote   -> send 100% of traffic to the latest baton-api revision
#   scripts/deploy.sh agents    -> deploy baton-agents (Pub/Sub worker) from the image of the latest baton-api revision
#   (the Baton website is a separate service: aegis_flow/scripts/deploy_web.sh)
set -euo pipefail

PROJECT="${PROJECT:-ai-builder-cup-2026-509818}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-baton-api}"
SA="baton-api@${PROJECT}.iam.gserviceaccount.com"
cd "$(dirname "$0")/.."

# Model IDs and locations live here (and only here), not in code.
ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT}"
ENV_VARS+=",GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.5-flash}"
ENV_VARS+=",GEMINI_FAST_MODEL=${GEMINI_FAST_MODEL:-gemini-3.5-flash-lite}"
ENV_VARS+=",GEMINI_LOCATION=${GEMINI_LOCATION:-asia-southeast1},GEMINI_FAST_LOCATION=${GEMINI_FAST_LOCATION:-global}"
ENV_VARS+=",EMBEDDING_MODEL=${EMBEDDING_MODEL:-gemini-embedding-001}"
ENV_VARS+=",EMBEDDING_LOCATION=${EMBEDDING_LOCATION:-asia-southeast1}"
ENV_VARS+=",EMBEDDING_DIM=${EMBEDDING_DIM:-768}"
ENV_VARS+=",TRANSCRIBE_ENGINE=${TRANSCRIBE_ENGINE:-gemini}"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
AGENTS_URL="https://baton-agents-${PROJECT_NUMBER}.${REGION}.run.app"
INVOKER="baton-pubsub-invoker@${PROJECT}.iam.gserviceaccount.com"

# The key that ships inside the public web app (and any APK given to judges). It opens the app endpoints only;
# acknowledging alerts and reading agent traces still need AEGIS_API_KEY. Create it once with scripts/setup_web.sh.
SECRETS="AEGIS_API_KEY=aegis-api-key:latest"
if gcloud secrets describe aegis-demo-key --project "$PROJECT" >/dev/null 2>&1; then
  SECRETS+=",AEGIS_DEMO_KEY=aegis-demo-key:latest"
fi

case "${1:-}" in
  canary)
    gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source . \
      --service-account "$SA" --allow-unauthenticated \
      --max-instances 5 --timeout 120 --cpu 1 --memory 1Gi \
      --set-env-vars "${ENV_VARS},PUBSUB_TOPIC=baton-handover-events,LEGACY_BRIEF_INLINE=${LEGACY_BRIEF_INLINE:-false}" \
      --set-secrets "$SECRETS" \
      --no-traffic --tag canary
    ;;
  promote)
    gcloud run services update-traffic "$SERVICE" --project "$PROJECT" --region "$REGION" --to-latest
    ;;
  agents)
    # Same image as baton-api, different start command. Not publicly invokable: only the push invoker may call it.
    REV="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.latestCreatedRevisionName)')"
    IMAGE="$(gcloud run revisions describe "$REV" --project "$PROJECT" --region "$REGION" --format='value(spec.containers[0].image)')"
    echo "baton-agents from image of $REV"
    gcloud run deploy baton-agents --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
      --service-account "baton-agents@${PROJECT}.iam.gserviceaccount.com" --no-allow-unauthenticated \
      --max-instances 5 --timeout 120 --cpu 1 --memory 1Gi \
      --command uvicorn --args "app.worker_main:app,--host,0.0.0.0,--port,8080" \
      --set-env-vars "${ENV_VARS},WORKER_AUDIENCE=${AGENTS_URL},PUSH_INVOKER_EMAIL=${INVOKER},PIPELINE_AGENTS_ENABLED=${PIPELINE_AGENTS_ENABLED:-true}"
    ;;
  *) echo "usage: $0 canary|promote|agents" >&2; exit 2 ;;
esac
