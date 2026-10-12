#!/usr/bin/env bash
# Recreate the background-pipeline infrastructure (topics, subscriptions, service accounts, IAM).
# These are the exact commands that built the live setup. Run once per project, after `deploy.sh agents`
# has created the baton-agents service. Re-running prints "already exists" for what is there.
#
# Note: new Cloud Run IAM bindings take about a minute to propagate, so the first push attempts may get 403.
set -uo pipefail
P="${PROJECT:-ai-builder-cup-2026-509818}"; R="${REGION:-asia-southeast1}"
N="$(gcloud projects describe "$P" --format='value(projectNumber)')"
URL="https://baton-agents-${N}.${R}.run.app"
AGENT_SA="baton-agents@${P}.iam.gserviceaccount.com"
INVOKER_SA="baton-pubsub-invoker@${P}.iam.gserviceaccount.com"
PUBSUB_AGENT="service-${N}@gcp-sa-pubsub.iam.gserviceaccount.com"

# 1. Topics (messages stay in-region) and the dead-letter holding subscription (a topic without one drops messages)
gcloud pubsub topics create baton-handover-events     --project "$P" --message-storage-policy-allowed-regions="$R"
gcloud pubsub topics create baton-handover-events-dlq --project "$P" --message-storage-policy-allowed-regions="$R"
gcloud pubsub subscriptions create baton-handover-events-dlq-hold --project "$P" --topic=baton-handover-events-dlq --message-retention-duration=7d

# 2. Service accounts
gcloud iam service-accounts create baton-agents         --project "$P" --display-name="Baton agents worker"
gcloud iam service-accounts create baton-pubsub-invoker --project "$P" --display-name="Pub/Sub push invoker"

# 3. The worker gets only what it needs
for ROLE in roles/aiplatform.user roles/datastore.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:${AGENT_SA}" --role="$ROLE" --condition=None --quiet >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://${P}-baton-corpus" --member="serviceAccount:${AGENT_SA}" --role=roles/storage.objectViewer

# 4. baton-api may publish to the one topic
gcloud pubsub topics add-iam-policy-binding baton-handover-events --project "$P" \
  --member="serviceAccount:baton-api@${P}.iam.gserviceaccount.com" --role=roles/pubsub.publisher

# 5. Only the push invoker may call the (private) worker
gcloud run services add-iam-policy-binding baton-agents --project "$P" --region "$R" \
  --member="serviceAccount:${INVOKER_SA}" --role=roles/run.invoker

# 6. The Pub/Sub service agent: mint OIDC tokens for the invoker, publish to the dead-letter topic
gcloud iam service-accounts add-iam-policy-binding "$INVOKER_SA" --project "$P" \
  --member="serviceAccount:${PUBSUB_AGENT}" --role=roles/iam.serviceAccountTokenCreator
gcloud pubsub topics add-iam-policy-binding baton-handover-events-dlq --project "$P" \
  --member="serviceAccount:${PUBSUB_AGENT}" --role=roles/pubsub.publisher

# 7. Push subscription: OIDC auth, 120 s ack deadline (matches the worker's 120 s timeout), 5 attempts then dead-letter
gcloud pubsub subscriptions create baton-handover-events-push --project "$P" --topic=baton-handover-events \
  --push-endpoint="${URL}/pubsub/handover" --push-auth-service-account="$INVOKER_SA" --push-auth-token-audience="$URL" \
  --ack-deadline=120 --min-retry-delay=10s --max-retry-delay=300s \
  --dead-letter-topic=baton-handover-events-dlq --max-delivery-attempts=5
gcloud pubsub subscriptions add-iam-policy-binding baton-handover-events-push --project "$P" \
  --member="serviceAccount:${PUBSUB_AGENT}" --role=roles/pubsub.subscriber
