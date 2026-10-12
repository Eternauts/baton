"""Shared helpers for the eval and load-test scripts. They talk to the deployed service and to Firestore
with the developer's own credentials (gcloud / ADC); nothing here is used by the running service."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "ai-builder-cup-2026-509818")
TERMINAL = ("completed", "fallback", "failed")


def api_key() -> str:
    """Read the key from Secret Manager into memory. It is never printed."""
    return subprocess.check_output(["gcloud", "secrets", "versions", "access", "latest", "--secret=aegis-api-key",
                                    "--project", PROJECT], text=True).strip()


def call(base: str, method: str, path: str, body: dict | None = None, key: str | None = None, timeout: int = 90):
    """Returns (status_code, json_or_None, elapsed_ms). Never raises on HTTP errors."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Aegis-Key"] = key
    req = urllib.request.Request(base.rstrip("/") + path, json.dumps(body).encode() if body is not None else None, headers, method=method)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r), (time.time() - t) * 1000
    except urllib.error.HTTPError as e:
        try:
            payload = json.load(e)
        except Exception:  # noqa: BLE001
            payload = None
        return e.code, payload, (time.time() - t) * 1000
    except Exception:  # noqa: BLE001 - timeouts, connection resets
        return 0, None, (time.time() - t) * 1000


def firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT)


def wait_for_runs(db, run_ids: list[str], timeout_s: int = 240, poll_s: int = 3) -> dict[str, dict | None]:
    """Poll agent_runs until every run is terminal or the time is up. Missing runs come back as None."""
    out: dict[str, dict | None] = {r: None for r in run_ids}
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for rid in run_ids:
            if out[rid] is None or out[rid].get("status") not in TERMINAL:
                d = db.collection("agent_runs").document(rid).get()
                out[rid] = d.to_dict() if d.exists else None
        if all(v and v.get("status") in TERMINAL for v in out.values()):
            break
        time.sleep(poll_s)
    return out


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]


def stats(values: list[float]) -> str:
    if not values:
        return "n=0"
    return f"n={len(values)} median {percentile(values, .5):.0f} p90 {percentile(values, .9):.0f} max {max(values):.0f} ms"


def delete_by_handover_ids(db, ids: list[str]) -> int:
    """Delete everything a set of test handovers produced (events, sessions, briefs, updates, runs+steps, capsules, chunks)."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    refs = []
    for i in ids:
        for col, doc in (("batch_sync_events", i), ("handover_sessions", i), ("handover_briefs", i),
                         ("device_updates", "upd-" + i), ("agent_runs", "run-" + i)):
            refs.append(db.collection(col).document(doc))
        refs += [d.reference for d in db.collection("agent_runs").document("run-" + i).collection("steps").select([]).stream()]
        refs += [d.reference for d in db.collection("handover_capsules").where(filter=FieldFilter("handover_id", "==", i)).select([]).stream()]
        refs += [d.reference for d in db.collection("knowledge_chunks").where(filter=FieldFilter("source_id", "==", i)).select([]).stream()]
    for k in range(0, len(refs), 400):
        b = db.batch()
        for r in refs[k:k + 400]:
            b.delete(r)
        b.commit()
    return len(refs)
