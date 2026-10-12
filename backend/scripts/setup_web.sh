#!/usr/bin/env bash
# One-time setup for the public web app: a separate key that is safe to ship inside a web page.
# It opens the app endpoints (transcribe, ask, extract, handover interview, device updates) but never the supervisor ones
# (acknowledge an alert, read agent traces). Rotate it any time: add a new version, redeploy with `deploy.sh web`.
set -euo pipefail
PROJECT="${PROJECT:-ai-builder-cup-2026-509818}"
SA="baton-api@${PROJECT}.iam.gserviceaccount.com"

if gcloud secrets describe aegis-demo-key --project "$PROJECT" >/dev/null 2>&1; then
  echo "secret aegis-demo-key already exists"
else
  openssl rand -hex 24 | tr -d '\n' | gcloud secrets create aegis-demo-key --project "$PROJECT" --replication-policy=automatic --data-file=-
  echo "created secret aegis-demo-key"
fi
gcloud secrets add-iam-policy-binding aegis-demo-key --project "$PROJECT" \
  --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor >/dev/null
echo "granted ${SA} access to aegis-demo-key"
