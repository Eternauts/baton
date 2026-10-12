"""Evaluate retrieval, grounded answers, guardrails and rule-verdict preservation against the deployed service.

    python -m eval.run_eval --url https://baton-api-....run.app [--reseed] [--keep]

Needs gcloud/ADC credentials (reads the API key from Secret Manager, reads and cleans Firestore).
Exit code is 1 if verdict preservation or citation validity is below 100%.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from eval.common import PROJECT, api_key, call, delete_by_handover_ids, firestore_client, percentile, stats, wait_for_runs  # noqa: E402

HERE = os.path.dirname(__file__)
SEVERITY = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
STALE_SEED_HOURS = 60       # history searches look back 72 h; seeds older than this make history questions unfair


def seed_age_hours(db) -> float | None:
    from google.cloud.firestore_v1.base_query import FieldFilter
    ages = []
    for d in db.collection("knowledge_chunks").where(filter=FieldFilter("seeded", "==", True)).select(["created_at"]).stream():
        c = d.to_dict().get("created_at")
        if c:
            ages.append((datetime.now(timezone.utc) - c).total_seconds() / 3600)
    return max(ages) if ages else None


def retrieval_hit(question: str, expected: list[str]) -> tuple[bool, list[str]]:
    from app.knowledge.search import search
    hits = search(question, k=6)
    sources = [h.source_id for h in hits]
    return any(e in sources for e in expected), sources


def run_scenarios(base, key, db, gold, results):
    from app.agents.guardrails import find_clearing_language
    rows, handovers = [], []
    for sc in gold["scenarios"]:
        caps = [{"uuid": f"eval-{sc['id']}-{i}-{int(time.time()*1000)}", "timestamp": datetime.now(timezone.utc).isoformat(), "intent_severity": "INFO", **c}
                for i, c in enumerate(sc["capsules"])]
        code, resp, ms = call(base, "POST", "/api/v1/handover/batch_sync", {
            "device_id": "eval-run", "operator_id": "TECH-EVAL-00", "shift_name": "EVAL-SHIFT", "unit_name": gold["unit"], "capsules": caps})
        row = {"id": sc["id"], "name": sc["name"], "sync_ms": round(ms)}
        if code != 200 or not resp or not resp.get("pipeline_run_id"):
            row.update(error=f"sync failed (HTTP {code})", preserved=False)
            rows.append(row)
            continue
        hid = resp["pipeline_run_id"].removeprefix("run-")
        handovers.append(hid)
        row.update(handover_id=hid, run_id=resp["pipeline_run_id"], rules_in_sync=sorted((c["rule_id"], c["severity"]) for c in resp["conflicts"]))
        rows.append(row)
    runs = wait_for_runs(db, [r["run_id"] for r in rows if "run_id" in r])
    for row in rows:
        if "run_id" not in row:
            continue
        run = runs.get(row["run_id"]) or {}
        sc = next(s for s in gold["scenarios"] if s["id"] == row["id"])
        brief = (db.collection("handover_briefs").document(row["handover_id"]).get().to_dict() or {})
        items = brief.get("items", [])
        expected = [(v["rule_id"], v["severity"]) for v in sc["expected_verdicts"]]
        missing = [e for e in expected if not any(i.get("rule_id") == e[0] and SEVERITY[i["severity"]] >= SEVERITY[e[1]] for i in items)]
        rules_match = sorted(expected) == row["rules_in_sync"]
        text = brief.get("headline", "") + " " + " ".join(i.get("text", "") for i in items)
        false_alert = sc.get("must_not_have_critical") and any(i["severity"] == "CRITICAL" for i in items)
        steps = [d.to_dict() for d in db.collection("agent_runs").document(row["run_id"]).collection("steps").stream()]
        lat = {}
        for s in steps:
            if s["kind"] == "agent_end" and s.get("latency_ms") is not None:
                lat[s["agent"]] = s["latency_ms"]
        row.update(status=run.get("status"), pipeline_ms=run.get("total_ms"), guardrails=run.get("guardrails_triggered", []),
                   brief_status=brief.get("guardrail_status"), missing_verdicts=missing, deterministic_rules_match_expected=rules_match,
                   false_critical=bool(false_alert), clearing_language=find_clearing_language(text),
                   agent_ms={k: lat[k] for k in ("SOPRetrieverLlm", "HistoryRetrieverLlm", "SafetyCrossCheckLlm", "BriefingLlm", "RulesGate") if k in lat},
                   preserved=not missing and rules_match and not false_alert and not find_clearing_language(text))
    results["scenarios"] = rows
    return handovers


def run_questions(base, key, db, gold, results, history_ok):
    rows = []
    for q in gold["questions"]:
        row = {"id": q["id"], "q": q["text"][:60], "expected": q["expected"]}
        if q.get("history") and not history_ok:
            row["skipped"] = "seed data too old for the 72 h history window; rerun with --reseed"
            rows.append(row)
            continue
        hit, sources = retrieval_hit(q["text"], q["expected"])
        body = {"question": q["text"], "unit": gold["unit"], "device_id": "eval-run"}
        if q.get("asset_tag"):
            body["asset_tag"] = q["asset_tag"]
        code, resp, ms = call(base, "POST", "/api/v1/ask", body, key=key)
        row.update(retrieval_hit=hit, top_sources=sources, http=code, wall_ms=round(ms))
        if code == 200 and resp:
            cited = [c["source_id"] for c in resp["citations"]]
            valid = True
            for c in resp["citations"]:
                snap = db.collection("knowledge_chunks").document(c["chunk_id"]).get()
                if not snap.exists or snap.to_dict().get("source_id") != c["source_id"] or snap.to_dict().get("title") != c["title"]:
                    valid = False
            run = db.collection("agent_runs").document(resp["run_id"]).get().to_dict() or {}
            row.update(answer_cites_expected=any(e in cited for e in q["expected"]), cited=sorted(set(cited)), citations_valid=valid,
                       latency_ms=resp["latency_ms"], status=run.get("status"), guardrails=run.get("guardrails_triggered", []),
                       lang=resp["answer_language"], has_verdicts=bool(resp["rule_verdicts"]), note=resp.get("confidence_note"))
        rows.append(row)
    results["questions"] = rows


def run_declines(base, key, db, gold, results):
    rows = []
    for d in gold["decline"]:
        code, resp, ms = call(base, "POST", "/api/v1/ask", {"question": d["text"], "unit": gold["unit"], "device_id": "eval-run"}, key=key)
        ok = code == 200 and resp is not None and resp["citations"] == [] and resp["rule_verdicts"] == [] and resp["answer"].strip() != ""
        run = (db.collection("agent_runs").document(resp["run_id"]).get().to_dict() or {}) if resp else {}
        rows.append({"id": d["id"], "declined_cleanly": ok and run.get("status") == "completed", "latency_ms": resp["latency_ms"] if resp else None})
    results["declines"] = rows


def summarize(results) -> dict:
    qs = [q for q in results["questions"] if "skipped" not in q and "retrieval_hit" in q]
    answered = [q for q in qs if "answer_cites_expected" in q]
    asks_ms = [q["latency_ms"] for q in answered]
    sc = results["scenarios"]
    pipe = [s["pipeline_ms"] for s in sc if s.get("pipeline_ms")]
    agent_ms: dict[str, list] = {}
    for s in sc:
        for k, v in s.get("agent_ms", {}).items():
            agent_ms.setdefault(k, []).append(v)
    return {
        "retrieval_hit_rate": f"{sum(q['retrieval_hit'] for q in qs)}/{len(qs)}",
        "answer_cites_expected": f"{sum(q['answer_cites_expected'] for q in answered)}/{len(answered)}",
        "citation_validity": f"{sum(q['citations_valid'] for q in answered)}/{len(answered)}",
        "asks_fallback": f"{sum(q['status'] == 'fallback' for q in answered)}/{len(answered)}",
        "ask_guardrail_triggers": sum(len(q['guardrails']) for q in answered),
        "declines_clean": f"{sum(d['declined_cleanly'] for d in results['declines'])}/{len(results['declines'])}",
        "verdict_preservation": f"{sum(s.get('preserved', False) for s in sc)}/{len(sc)}",
        "pipeline_fallbacks": f"{sum(s.get('status') == 'fallback' for s in sc)}/{len(sc)}",
        "pipeline_guardrail_triggers": sum(len(s.get('guardrails', [])) for s in sc),
        "ask_latency": stats(asks_ms), "pipeline_latency": stats(pipe),
        "agent_latency": {k: f"median {percentile(v, .5):.0f} max {max(v):.0f} ms" for k, v in agent_ms.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--reseed", action="store_true", help="delete and recreate the seeded demo handovers first")
    ap.add_argument("--keep", action="store_true", help="keep the scenario test data")
    args = ap.parse_args()
    gold = json.load(open(os.path.join(HERE, "golden.json"), encoding="utf-8"))
    key, db = api_key(), firestore_client()
    results: dict = {"url": args.url, "started": datetime.now(timezone.utc).isoformat()}

    if args.reseed:
        from scripts import seed_handovers
        seed_handovers.cleanup()
        seed_handovers.seed()
    age = seed_age_hours(db)
    history_ok = age is not None and age < STALE_SEED_HOURS
    print(f"seed data age: {'none' if age is None else f'{age:.0f} h'} -> history questions {'scored' if history_ok else 'SKIPPED'}")

    handovers = run_scenarios(args.url, key, db, gold, results)
    run_questions(args.url, key, db, gold, results, history_ok)
    run_declines(args.url, key, db, gold, results)
    results["summary"] = summarize(results)
    results["finished"] = datetime.now(timezone.utc).isoformat()

    path = os.path.join(HERE, "results", f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    json.dump(results, open(path, "w"), indent=2, default=str, ensure_ascii=False)

    print("\n== handover scenarios ==")
    for s in results["scenarios"]:
        print(f"{s['id']} {s['name']:40s} status={s.get('status')} preserved={s.get('preserved')} missing={s.get('missing_verdicts')} "
              f"pipeline={s.get('pipeline_ms')}ms guardrails={s.get('guardrails')}")
    print("\n== questions ==")
    for q in results["questions"]:
        if "skipped" in q:
            print(f"{q['id']} SKIPPED: {q['skipped']}")
        else:
            print(f"{q['id']} retrieval={'hit ' if q['retrieval_hit'] else 'MISS'} cites_expected={q.get('answer_cites_expected')} valid={q.get('citations_valid')} "
                  f"{q.get('latency_ms')}ms {q.get('status')} lang={q.get('lang')} cited={q.get('cited')}")
    print("\n== summary ==")
    for k, v in results["summary"].items():
        print(f"{k:30s} {v}")
    print(f"\nresults written to {path}")

    if not args.keep:
        deleted = delete_by_handover_ids(db, handovers)
        for r in db.collection("agent_runs").where("trigger", "==", "ask").stream():     # the eval's own ask traces
            if (r.to_dict().get("device_id") or "") == "eval-run":
                for st in r.reference.collection("steps").stream():
                    st.reference.delete()
                r.reference.delete()
                deleted += 1
        db.collection("devices").document("eval-run").delete()
        print(f"cleaned up {deleted} test documents")

    s = results["summary"]
    bad = s["verdict_preservation"].split("/")[0] != s["verdict_preservation"].split("/")[1] or s["citation_validity"].split("/")[0] != s["citation_validity"].split("/")[1]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
