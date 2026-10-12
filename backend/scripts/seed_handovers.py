"""Seed realistic past handovers for HYDROCRACKER-01 so cross-user retrieval has something to find.

    python -m scripts.seed_handovers            # write seeded handover_capsules + knowledge_chunks
    python -m scripts.seed_handovers --cleanup  # delete everything flagged seeded:true

Every seeded document carries seeded:true and ids starting with 'seed-'.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: E402

from app.knowledge.handover_chunker import chunk_handover  # noqa: E402
from app.knowledge.store import delete_seeded, get_db, upsert_chunks  # noqa: E402

UNIT = "HYDROCRACKER-01"


def _cap(uid, tag, cat, state, note, minutes_after_start, sev="INFO"):
    return {"uuid": uid, "asset_tag": tag, "category": cat, "asserted_state": state,
            "text_transcript": note, "intent_severity": sev, "_offset_min": minutes_after_start}


# (handover_id, shift, operator_id, hours_ago_shift_ended, capsules)
HANDOVERS = [
    ("seed-h1", "DAY-SHIFT-B", "TECH-RAVI-11", 40, [
        _cap("seed-c01", "P-201B", "EQUIPMENT", "RUNNING", "Seal weeping slightly, vibration 5 mm/s. Monitor each round.", 20),
        _cap("seed-c02", "V-102", "EQUIPMENT", "RUNNING", "Level control valve slow to respond, put on manual by Ravi.", 55)]),
    ("seed-h2", "DAY-SHIFT-B", "TECH-MEERA-07", 40, [
        _cap("seed-c03", "TK-501", "EQUIPMENT", "ACTIVE", "Level 78 percent, transfer in progress from unit.", 30),
        _cap("seed-c04", "ESDV-301", "ISOLATION", "CLOSED", "ESDV-301 tested closed, no bypass applied.", 70)]),
    ("seed-h3", "NIGHT-SHIFT-B", "TECH-ARUN-42", 28, [
        _cap("seed-c05", "P-201B", "EQUIPMENT", "RUNNING", "Vibrating heavily, seal looks wet. Maintenance requested, work order raised by Arun.", 25, "WARNING"),
        _cap("seed-c06", "P-201A", "EQUIPMENT", "STANDBY", "Standby pump checked and ready to take duty.", 40)]),
    ("seed-h4", "NIGHT-SHIFT-B", "TECH-PRIYA-09", 28, [
        _cap("seed-c07", "TK-501", "EQUIPMENT", "ACTIVE", "Level 82 percent and rising, transfer paused at supervisor request.", 35, "WARNING"),
        _cap("seed-c08", "V-102", "EQUIPMENT", "RUNNING", "Level control still on manual, valve sticking at 40 percent.", 60)]),
    ("seed-h5", "DAY-SHIFT-A", "TECH-RAVI-11", 16, [
        _cap("seed-c09", "P-201B", "EQUIPMENT", "RUNNING", "Vibration 7.5 mm/s, seal wet. Planned for isolation and seal replacement next shift.", 15, "WARNING"),
        _cap("seed-c10", "P-201A", "EQUIPMENT", "RUNNING", "Duty moved to P-201A at 11:30 as precaution.", 45)]),
    ("seed-h6", "DAY-SHIFT-A", "TECH-MEERA-07", 16, [
        _cap("seed-c11", "ESDV-301", "ISOLATION", "BYPASSED", "Bypass applied for partial stroke test, approved by supervisor, expected back in 2 hours.", 50, "WARNING"),
        _cap("seed-c12", "TK-501", "EQUIPMENT", "ACTIVE", "Level 80 percent, manual readings every 30 minutes while bypass is on.", 80)]),
    ("seed-h7", "DAY-SHIFT-A", "TECH-SURESH-23", 16, [
        _cap("seed-c13", "V-102", "EQUIPMENT", "RUNNING", "Level control valve repaired and returned to auto.", 30),
        _cap("seed-c14", "P-201B", "ISOLATION", "NOT ISOLATED", "P-201B still running, isolation not yet done. Next shift to isolate before seal work.", 100, "CRITICAL")]),
]


def build(now: datetime):
    for hid, shift, op, hours_ago, caps in HANDOVERS:
        start = now - timedelta(hours=hours_ago + 8)
        out = []
        for c in caps:
            c = dict(c)
            c["timestamp"] = (start + timedelta(minutes=c.pop("_offset_min"))).isoformat()
            out.append(c)
        yield hid, shift, op, out


def seed() -> None:
    db = get_db()
    now = datetime.now(timezone.utc)
    chunks, n_caps = [], 0
    for hid, shift, op, caps in build(now):
        batch = db.batch()
        for c in caps:
            batch.set(db.collection("handover_capsules").document(c["uuid"]), {
                **c, "handover_id": hid, "unit_name": UNIT, "shift_name": shift, "operator_id": op,
                "device_id": "seed", "created_at": datetime.fromisoformat(c["timestamp"]), "seeded": True})
            n_caps += 1
        batch.commit()
        chunks += chunk_handover(hid, caps, unit_name=UNIT, shift_name=shift, operator_id=op, seeded=True)
    n = upsert_chunks(chunks)
    print(f"seeded {len(HANDOVERS)} handovers, {n_caps} capsules, {n} chunks (all seeded:true)")


def cleanup() -> None:
    db = get_db()
    chunks = delete_seeded()
    refs = [d.reference for d in db.collection("handover_capsules")
            .where(filter=FieldFilter("seeded", "==", True)).select([]).stream()]
    for ref in refs:
        ref.delete()
    print(f"deleted {chunks} seeded chunks and {len(refs)} seeded capsules")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cleanup() if args.cleanup else seed()
