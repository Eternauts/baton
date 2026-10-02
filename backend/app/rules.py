from __future__ import annotations
from typing import List, Dict, Any
from app.models import Fact, SafetyConflict, Severity


class SafetyRulesEngine:
    """
    Deterministic Safety Rules Engine (R1 - R5).
    Rules execute purely deterministically on extracted facts and live plant state.
    """

    def evaluate(
        self,
        facts: List[Fact],
        plant_state: Dict[str, Any],
        permits: List[Dict[str, Any]]
    ) -> List[SafetyConflict]:
        conflicts: List[SafetyConflict] = []
        fact_map = {f.id: f for f in facts}

        # Rule R1: Isolation Mismatch (Logged Isolated, but Plant Active)
        for fact in facts:
            if "ISOLATED" in fact.text.upper() or "REMOVED" in fact.text.upper():
                # Extract potential tag name or look in plant state
                for tag, state in plant_state.items():
                    if tag.lower() in fact.text.lower() and state in ["OPEN", "RUNNING", "ACTIVE", "ENERGIZED"]:
                        conflicts.append(
                            SafetyConflict(
                                id=f"CONF-R1-{len(conflicts)+1}",
                                rule_id="R1",
                                title=f"Isolation Mismatch: {tag}",
                                description=f"Log states '{fact.text}', but live plant state for {tag} is physically '{state}'.",
                                severity=Severity.CRITICAL,
                                evidence_ids=[fact.id, f"PLANT-{tag}"]
                            )
                        )

        # Rule R2: SIMOPS Conflict (Hot Work near Open Containment)
        has_hot_work = any(
            p.get("type", "").upper() == "HOT_WORK" or "HOT WORK" in str(p).upper()
            for p in permits
        )
        has_containment_break = any(
            "FLANGE" in f.text.upper() or "OPEN LINE" in f.text.upper() or "OPEN CONTAINMENT" in f.text.upper()
            for f in facts
        )
        if has_hot_work and has_containment_break:
            hot_work_permit = next((p for p in permits if "HOT" in p.get("type", "").upper()), {})
            open_fact = next((f for f in facts if "FLANGE" in f.text.upper() or "OPEN" in f.text.upper()), None)
            ev_ids = [open_fact.id] if open_fact else []
            if hot_work_permit.get("id"):
                ev_ids.append(hot_work_permit["id"])

            conflicts.append(
                SafetyConflict(
                    id=f"CONF-R2-{len(conflicts)+1}",
                    rule_id="R2",
                    title="SIMOPS Hazard: Hot Work near Open Line/Flange",
                    description="Active Hot Work permit is registered while equipment line/flange is open to atmosphere.",
                    severity=Severity.CRITICAL,
                    evidence_ids=ev_ids
                )
            )

        # Rule R3: Bypassed Safety Interlock
        for tag, state in plant_state.items():
            if "BYPASS" in tag.upper() and state in [True, "TRUE", "ACTIVE", "BYPASSED"]:
                matching_fact = next((f for f in facts if tag.lower() in f.text.lower()), None)
                ev_ids = [f"PLANT-{tag}"]
                if matching_fact:
                    ev_ids.append(matching_fact.id)

                conflicts.append(
                    SafetyConflict(
                        id=f"CONF-R3-{len(conflicts)+1}",
                        rule_id="R3",
                        title=f"Unflagged Safeguard Bypass: {tag}",
                        description=f"Safety interlock/detector '{tag}' is actively BYPASSED in control system.",
                        severity=Severity.WARNING if matching_fact else Severity.CRITICAL,
                        evidence_ids=ev_ids
                    )
                )

        # Rule R4: Unclosed or Expired Work Permit
        for permit in permits:
            status = permit.get("status", "").upper()
            permit_id = permit.get("id", "PERMIT-UNKNOWN")
            if status == "EXPIRED" or (status == "OPEN" and permit.get("expired", False)):
                conflicts.append(
                    SafetyConflict(
                        id=f"CONF-R4-{len(conflicts)+1}",
                        rule_id="R4",
                        title=f"Expired Maintenance Permit Active: {permit_id}",
                        description=f"Permit {permit_id} ({permit.get('title', 'Maintenance')}) has expired but was not formally closed out.",
                        severity=Severity.WARNING,
                        evidence_ids=[permit_id]
                    )
                )

        return conflicts
