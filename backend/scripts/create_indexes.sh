#!/usr/bin/env bash
# Recreate the knowledge_chunks vector indexes (keep in sync with firestore.indexes.json).
# Vector dimension must match EMBEDDING_DIM. Re-running is safe: existing indexes are skipped.
set -uo pipefail
PROJECT="${PROJECT:-ai-builder-cup-2026-509818}"
DIM="${EMBEDDING_DIM:-768}"
VEC="field-path=embedding,vector-config={\"dimension\":\"${DIM}\",\"flat\":\"{}\"}"

create() {
  gcloud firestore indexes composite create --project "$PROJECT" --database='(default)' \
    --collection-group=knowledge_chunks --query-scope=COLLECTION --async "$@" 2>&1 \
    | grep -v -i "already exists" || true
}

create --field-config="$VEC"
create --field-config=field-path=source_type,order=ascending --field-config="$VEC"
create --field-config=field-path=unit,order=ascending --field-config="$VEC"
create --field-config=field-path=asset_tags,array-config=contains --field-config="$VEC"
create --field-config=field-path=unit,order=ascending --field-config=field-path=source_type,order=ascending --field-config="$VEC"
create --field-config=field-path=unit,order=ascending --field-config=field-path=asset_tags,array-config=contains --field-config="$VEC"
echo "Submitted. Check status with: gcloud firestore indexes composite list --project $PROJECT"

# Device updates: GET /api/v1/devices/{id}/updates (unit equal, newest first)
gcloud firestore indexes composite create --project "$PROJECT" --database='(default)' --collection-group=device_updates \
  --query-scope=COLLECTION --field-config=field-path=unit,order=ascending --field-config=field-path=created_at,order=descending --async 2>&1 \
  | grep -v -i "already exists" || true
