"""Tools the agents may call. Plain Python functions with type hints and docstrings (ADK reads both).

`make_tools(run_ctx)` returns closures bound to one run, so the tools can record what they retrieved
(used later to verify citations) without the model passing any internal state.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.agents.guardrails import is_unresolved, map_status
from app.agents.schemas import RuleVerdict
from app.knowledge.search import search as knowledge_search
from app.knowledge.store import get_db
from app.knowledge.tags import extract_asset_tags, normalize_tag, normalize_unit
from app.plant_data import MOCK_ACTIVE_PERMITS, MOCK_DCS_TELEMETRY
from app.safety import evaluate_capsules

EVENTS = "batch_sync_events"
SESSIONS = "handover_sessions"
MAX_HITS = 4
MAX_TEXT = 500
OPEN_CONFLICT_WINDOW = timedelta(hours=24)


def load_event(handover_id: str) -> Optional[dict]:
    snap = get_db().collection(EVENTS).document(handover_id).get()
    return snap.to_dict() if snap.exists else None


def asset_of(rule_id: str, evidence_ids: list) -> Optional[str]:
    """The asset a verdict is about: the plant-feed tag for R1/R3, the permit ID for R4, none for R2."""
    if rule_id in ("R1", "R3"):
        return next((e[4:] for e in evidence_ids if str(e).startswith("DCS-")), None)
    if rule_id == "R4":
        return evidence_ids[0] if evidence_ids else None
    return None


def verdict_from_conflict(c: Any) -> RuleVerdict:
    asset = asset_of(c.rule_id, list(c.evidence_ids))
    return RuleVerdict(verdict_id=c.id, rule_id=c.rule_id, severity=c.severity.value if hasattr(c.severity, "value") else str(c.severity),
                       asset_tag=asset, title=c.title, description=c.description, evidence_ids=list(c.evidence_ids))


def compute_verdicts(capsules: list[dict]) -> list[RuleVerdict]:
    return [verdict_from_conflict(c) for c in evaluate_capsules(capsules)]


def _compact_hit(h) -> dict:
    return {"chunk_id": h.chunk_id, "source_type": h.source_type, "source_id": h.source_id, "title": h.title,
            "text": h.text[:MAX_TEXT], "distance": round(h.distance, 3), "asset_tags": h.asset_tags[:6],
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "supersedes": h.supersedes}


def make_tools(run_ctx) -> dict[str, Callable]:
    def _remember(hits) -> list[dict]:
        out = []
        for h in hits:
            c = _compact_hit(h)
            run_ctx.retrieved[c["chunk_id"]] = c
            out.append(c)
        return out

    def search_sops(query: str, asset_tag: str = "") -> dict:
        """Search the plant's standard operating procedures, bulletins and manuals.

        Args:
            query: What to look for, in plain words (any language).
            asset_tag: Optional equipment tag such as P-201B to narrow the search. Leave empty if unsure.

        Returns:
            A dict with `hits`, each having chunk_id, title, text, distance and `supersedes` (set when a
            bulletin overrides a section of another SOP).
        """
        hits = knowledge_search(query, k=MAX_HITS, source_types=["SOP"], asset_tag=asset_tag or None)
        return {"hits": _remember(hits)}

    def search_history(query: str, unit: str = "", asset_tag: str = "", since_hours: int = 72) -> dict:
        """Search earlier handovers and field observations from other shifts.

        Args:
            query: What to look for, in plain words.
            unit: Plant unit. Leave empty to use the unit of the handover being checked.
            asset_tag: Optional equipment tag such as P-201B.
            since_hours: How far back to look (default 72).

        Returns:
            A dict with `hits`, each having chunk_id, title, text, created_at and distance.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(int(since_hours), 24 * 14)))
        hits = knowledge_search(query, k=MAX_HITS + 2, source_types=["HANDOVER", "OBSERVATION"],
                                unit=unit or run_ctx.unit, asset_tag=asset_tag or None, since=since)
        hits = [h for h in hits if h.source_id != run_ctx.handover_id][:MAX_HITS]   # other shifts only
        return {"hits": _remember(hits)}

    def get_scada(asset_tags: list[str]) -> dict:
        """Current readings from the simulated plant feed (not live telemetry) for the given equipment tags.

        Args:
            asset_tags: Equipment tags such as ["P-201B", "TK-501"].

        Returns:
            A dict mapping each known tag to its readings. Unknown tags are listed under `unknown`.
        """
        tags = [normalize_tag(t) for t in asset_tags][:10]
        known = {t: MOCK_DCS_TELEMETRY[t] for t in tags if t in MOCK_DCS_TELEMETRY}
        return {"source": "simulated plant feed", "readings": known, "unknown": [t for t in tags if t not in known]}

    def evaluate_rules(handover_id: str) -> dict:
        """Run the deterministic safety rules R1 to R4 for a handover. The verdicts are final.

        Args:
            handover_id: The handover to evaluate.

        Returns:
            A dict with `verdicts`: rule_id, severity, asset_tag, title, description and evidence_ids.
        """
        cap_event = load_event(handover_id) if handover_id != run_ctx.handover_id or not run_ctx.capsules else None
        capsules = run_ctx.capsules if run_ctx.capsules and handover_id == run_ctx.handover_id else (cap_event or {}).get("capsules", [])
        return {"verdicts": [v.model_dump() for v in compute_verdicts(capsules)]}

    def get_handover(handover_id: str) -> dict:
        """Load the facts logged in a handover, and the outgoing operator's interview answers if present.

        Args:
            handover_id: The handover to load.

        Returns:
            A dict with unit, shift, `facts` (asset_tag, state, category, note) and `answers`.
        """
        ev = load_event(handover_id)
        if not ev:
            return {"error": "handover not found"}
        snap = get_db().collection(SESSIONS).document(handover_id).get()
        qs = (snap.to_dict() or {}).get("questions", []) if snap.exists else []
        return {"unit": ev.get("unit_name"), "shift": ev.get("shift_name"),
                "facts": [{"asset_tag": c.get("asset_tag"), "state": c.get("asserted_state"), "category": c.get("category"),
                           "note": (c.get("text_transcript") or "")[:300]} for c in (ev.get("capsules") or [])][:20],
                "answers": [{"question": q.get("question_text", "")[:200], "answer": q.get("answer_text")}
                            for q in qs if q.get("answered")][:5]}

    def get_open_conflicts(unit: str) -> dict:
        """List conflicts in a unit that are still open or only acknowledged (never resolved) in the last 24 hours.

        Args:
            unit: Plant unit, for example HYDROCRACKER-01.

        Returns:
            A dict with `conflicts`: one row per distinct conflict (rule, asset, title) with rule_id, severity,
            asset_tag, title, status (OPEN or ACKNOWLEDGED, taken from the newest report), handover_id (the
            newest report) and `reports`, how many handovers in the window raised it.
        """
        want = normalize_unit(unit)
        cutoff = datetime.now(timezone.utc) - OPEN_CONFLICT_WINDOW
        rows: dict = {}
        # newest sessions first; filtered by unit here so no composite index is needed
        for d in get_db().collection(SESSIONS).order_by("created_at", direction="DESCENDING").limit(60).stream():
            s = d.to_dict()
            if normalize_unit(s.get("unit_name")) != want:
                continue
            try:
                created = datetime.fromisoformat(str(s.get("created_at")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                continue
            for c in s.get("conflicts", []):
                if is_unresolved(c.get("status")):
                    asset = asset_of(c.get("rule_id", ""), c.get("evidence_ids") or [])
                    key = (c.get("rule_id"), asset, c.get("title"))
                    if key in rows:
                        rows[key]["reports"] += 1     # the same conflict reported again: count it, do not list it again
                        continue
                    rows[key] = {"rule_id": c.get("rule_id"), "severity": str(c.get("severity", "WARNING")).upper(),
                                 "asset_tag": asset, "title": c.get("title"), "status": map_status(c.get("status")),
                                 "handover_id": s.get("id"), "reports": 1}
        return {"conflicts": list(rows.values())[:15]}

    return {f.__name__: f for f in (search_sops, search_history, get_scada, evaluate_rules, get_handover, get_open_conflicts)}
