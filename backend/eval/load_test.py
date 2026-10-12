"""Light load test: N syncs spread over a window, then verify nothing was lost, duplicated or dead-lettered.

    python -m eval.load_test --url https://baton-api-....run.app [--n 20] [--window 60] [--keep]

Uses the test unit LOAD-TEST-UNIT and devices loadtest-N. Test data is deleted at the end unless --keep.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from eval.common import PROJECT, api_key, call, delete_by_handover_ids, firestore_client, percentile, stats, wait_for_runs  # noqa: E402

UNIT = "LOAD-TEST-UNIT"


def payload(i: int) -> dict:
    if i % 2 == 0:       # conflict handover
        cap = {"category": "ISOLATION", "asset_tag": "P-201B", "asserted_state": "ISOLATED", "text_transcript": f"Pump P-201B isolated and lock applied, load test {i}."}
    else:                # uneventful handover
        cap = {"category": "EQUIPMENT", "asset_tag": "V-102", "asserted_state": "CLOSED", "text_transcript": f"Drum V-102 normal readings, load test {i}."}
    cap.update(uuid=f"load-{i}-{int(time.time()*1000)}", timestamp=datetime.now(timezone.utc).isoformat(), intent_severity="INFO")
    return {"device_id": f"loadtest-{i}", "operator_id": "TECH-LOAD-00", "shift_name": "LOAD-SHIFT", "unit_name": UNIT, "capsules": [cap]}


def count(db, col: str, field: str, value) -> int:
    from google.cloud.firestore_v1.base_query import FieldFilter
    return sum(1 for _ in db.collection(col).where(filter=FieldFilter(field, "==", value)).select([]).stream())


def gcloud_lines(args: list[str]) -> list[str]:
    out = subprocess.run(["gcloud"] + args, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--wait", type=int, default=300, help="seconds to let the pipeline drain")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    db = firestore_client()
    started_iso = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    results: list[dict] = [None] * args.n          # type: ignore[list-item]

    def fire(i: int):
        time.sleep(max(0.0, i * args.window / args.n - (time.time() - t0)))
        code, resp, ms = call(args.url, "POST", "/api/v1/handover/batch_sync", payload(i))
        results[i] = {"i": i, "http": code, "ms": ms, "resp": resp}

    with ThreadPoolExecutor(max_workers=args.n) as ex:
        list(ex.map(fire, range(args.n)))
    sync_ok = [r for r in results if r["http"] == 200 and r["resp"] and r["resp"].get("pipeline_run_id")]
    print(f"sent {args.n} syncs over {time.time() - t0:.0f}s | HTTP 200 with pipeline_run_id: {len(sync_ok)}/{args.n}")
    print("sync latency:", stats([r["ms"] for r in results if r["http"] == 200]))
    print("sync failures:", Counter(r["http"] for r in results if r["http"] != 200) or "none")

    run_ids = [r["resp"]["pipeline_run_id"] for r in sync_ok]
    handovers = [r.removeprefix("run-") for r in run_ids]
    print(f"waiting up to {args.wait}s for the pipeline to drain...")
    runs = wait_for_runs(db, run_ids, timeout_s=args.wait)
    status = Counter((v or {}).get("status", "MISSING") for v in runs.values())
    drained_s = time.time() - t0
    print(f"\nrun statuses: {dict(status)} (drained after {drained_s:.0f}s from first send)")

    # duplicates and losses
    dup_runs = [rid for rid, v in runs.items() if v and v.get("attempts", 1) != 1]
    chunks_per = {h: count(db, "knowledge_chunks", "source_id", h) for h in handovers}
    caps_per = {h: count(db, "handover_capsules", "handover_id", h) for h in handovers}
    run_docs = count(db, "agent_runs", "unit", UNIT)
    print(f"runs with attempts != 1 (redelivered/retried): {len(dup_runs)}")
    print(f"agent_runs documents for the test unit: {run_docs} (expected {len(run_ids)})")
    print(f"chunks per handover: {dict(Counter(chunks_per.values()))} | capsule records per handover: {dict(Counter(caps_per.values()))} (expected exactly 1 each)")

    # dead letters and errors
    dlq = gcloud_lines(["pubsub", "subscriptions", "pull", "baton-handover-events-dlq-hold", "--project", PROJECT, "--limit=20", "--format=value(message.messageId)"])
    print(f"dead-letter hold backlog: {len(dlq)}")
    logs = gcloud_lines(["logging", "read", f'resource.type="cloud_run_revision" AND resource.labels.service_name="baton-agents" AND timestamp>="{started_iso}" '
                         'AND (textPayload:"Memory limit" OR textPayload:"out of memory" OR severity>=ERROR)', "--project", PROJECT, "--limit=20", "--format=value(severity,textPayload)"])
    print(f"worker error/OOM log lines since start: {len(logs)}")
    for l in logs[:5]:
        print("   ", l[:160])
    starts = gcloud_lines(["logging", "read", f'resource.type="cloud_run_revision" AND resource.labels.service_name="baton-agents" AND timestamp>="{started_iso}" AND textPayload:"Starting new instance"',
                           "--project", PROJECT, "--limit=50", "--format=value(timestamp)"])
    print(f"worker instances started during the test: {len(starts)}")

    # pipeline quality under load
    totals = [v["total_ms"] for v in runs.values() if v and v.get("total_ms")]
    print("\npipeline total:", stats(totals))
    fallbacks = {rid: v.get("guardrails_triggered") for rid, v in runs.items() if v and v.get("status") == "fallback"}
    print(f"fallback runs: {len(fallbacks)}", Counter(g for gs in fallbacks.values() for g in (gs or [])) or "")
    for rid in fallbacks:            # show where the time went in a fallback run, before the cleanup deletes the trace
        steps = [d.to_dict() for d in db.collection("agent_runs").document(rid).collection("steps").order_by("seq").stream()]
        t0 = steps[0]["timestamp"] if steps else None
        print(f"\n  trace of fallback run {rid}:")
        for st in steps:
            if st["kind"] in ("tool_call", "tool_result", "guardrail") or (st["kind"] == "agent_end" and st.get("latency_ms") and st["latency_ms"] > 4000):
                print(f"    +{(st['timestamp'] - t0).total_seconds():5.1f}s {st['kind']:12s} {st['agent']:22s} {st.get('latency_ms') or '':>6} {st['summary'][:70]}")
    failed = [rid for rid, v in runs.items() if not v or v.get("status") != "completed" and v.get("status") != "fallback"]

    ok = (len(sync_ok) == args.n and not failed and not dup_runs and run_docs == len(run_ids)
          and all(c == 1 for c in chunks_per.values()) and all(c == 1 for c in caps_per.values()) and not dlq)
    print("\nRESULT:", "PASS (no failed syncs, no lost or duplicate runs, no dead letters)" if ok else "FAIL - see above")

    if not args.keep:
        print(f"cleaned up {delete_by_handover_ids(db, handovers)} test documents")
        for i in range(args.n):
            db.collection("devices").document(f"loadtest-{i}").delete()
    json.dump({"statuses": dict(status), "totals_ms": totals, "sync_ms": [r["ms"] for r in results]}, open("eval/results/load-latest.json", "w"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
