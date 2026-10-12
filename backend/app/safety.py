"""One place that turns capsules into facts and runs the deterministic rules.
Both the sync endpoint and the background pipeline call this, so they can never disagree."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models import Fact, SafetyConflict, Severity
from app.plant_data import MOCK_ACTIVE_PERMITS, MOCK_DCS_TELEMETRY
from app.rules import SafetyRulesEngine

_engine = SafetyRulesEngine()


def facts_from_capsules(capsules: List[Dict[str, Any]]) -> List[Fact]:
    """Same fact text the sync endpoint has always built, so the rules see identical input."""
    facts = []
    for c in capsules:
        text = f"Asset {c['asset_tag']} asserted as {c['asserted_state']}. {c.get('text_transcript', '')}".strip()
        facts.append(Fact(id=c["uuid"], text=text, category=str(c.get("category", "EQUIPMENT")).upper(),
                          source_type="ON_DEVICE_GEMMA", source_id=c["uuid"]))
    return facts


def evaluate_capsules(capsules: List[Dict[str, Any]], telemetry: Optional[Dict[str, Any]] = None,
                      permits: Optional[List[Dict[str, Any]]] = None) -> List[SafetyConflict]:
    return _engine.evaluate(facts_from_capsules(capsules),
                            MOCK_DCS_TELEMETRY if telemetry is None else telemetry,
                            MOCK_ACTIVE_PERMITS if permits is None else permits)


def has_critical(conflicts: List[SafetyConflict]) -> bool:
    return any(c.rule_id in ("R1", "R2") or c.severity == Severity.CRITICAL for c in conflicts)
