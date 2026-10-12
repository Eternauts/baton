"""Deterministic assessment, brief and device update built only from rule verdicts. No model involved."""
from __future__ import annotations

from app.agents.schemas import (SEVERITY_RANK, AssessmentItem, BriefLine, DeviceUpdate, RuleVerdict,
                                SafetyAssessment, ShiftBrief)

_ACTIONS = {
    "R1": "Physically verify the isolation of {asset} at the equipment before relying on the log.",
    "R2": "Stop hot work and confirm the open flange or line is blinded or closed before work continues.",
    "R3": "Confirm the bypass of {asset} is approved, logged and covered by compensating measures.",
    "R4": "Close out or revalidate the expired permit {asset} before work continues.",
}
_DEFAULT_ACTION = "Verify this condition in the field and report back to the supervisor."


def action_for(v: RuleVerdict) -> str:
    return _ACTIONS.get(v.rule_id, _DEFAULT_ACTION).format(asset=v.asset_tag or "the item")


def fallback_assessment(verdicts: list[RuleVerdict]) -> SafetyAssessment:
    return SafetyAssessment(items=[
        AssessmentItem(severity=v.severity, explanation=v.description[:700], source="rule", verdict_id=v.verdict_id,
                       rule_id=v.rule_id, asset_tag=v.asset_tag) for v in verdicts])


def fallback_brief(verdicts: list[RuleVerdict], n_capsules: int) -> ShiftBrief:
    ordered = sorted(verdicts, key=lambda v: -SEVERITY_RANK[v.severity])
    if not ordered:
        return ShiftBrief(headline=f"{n_capsules} log entries reviewed. No rule violations were raised by the automatic checks.", items=[])
    crit = sum(1 for v in ordered if v.severity == "CRITICAL")
    head = (f"{len(ordered)} safety conflict(s) are open ({crit} critical). Each one must be verified in the field "
            f"and read back before responsibility transfers.")
    return ShiftBrief(headline=head[:240], items=[
        BriefLine(severity=v.severity, text=f"[{v.rule_id}] {v.title}: {v.description}"[:400], rule_id=v.rule_id,
                  verdict_id=v.verdict_id, asset_tag=v.asset_tag) for v in ordered])


def build_device_update(handover_id: str, run_id: str, unit: str | None, brief: ShiftBrief,
                        verdicts: list[RuleVerdict], target: str = "all") -> DeviceUpdate:
    top = max((v.severity for v in verdicts), key=lambda s: SEVERITY_RANK[s], default="INFO")
    alerts = [f"[{v.rule_id}] {v.title}"[:160] for v in sorted(verdicts, key=lambda v: -SEVERITY_RANK[v.severity])]
    actions = list(dict.fromkeys(action_for(v) for v in verdicts))
    return DeviceUpdate(update_id=f"upd-{handover_id}", unit=unit, target=target, severity=top, alerts=alerts[:6],
                        required_actions=actions[:6], summary=brief.headline[:400], handover_id=handover_id, run_id=run_id)
