"""Deterministic checks applied after every model output. Rules decide; models explain.

A model may add advisory concerns. It may never remove, soften or contradict a rule verdict,
and it may never say a conflict is clear while one is open or only acknowledged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from app.agents.schemas import SEVERITY_RANK, RuleVerdict

# Conflict states. Only RESOLVED closes a conflict, and nothing in the system produces it yet,
# so every operator or supervisor action counts as ACKNOWLEDGED, never as resolved.
OPEN, ACKNOWLEDGED, RESOLVED = "OPEN", "ACKNOWLEDGED", "RESOLVED"
_STATUS_MAP = {"OPEN": OPEN, "CONFIRMED": ACKNOWLEDGED, "CLARIFIED": ACKNOWLEDGED, "MITIGATED": ACKNOWLEDGED,
               "ACKNOWLEDGED": ACKNOWLEDGED, "RESOLVED": RESOLVED}


def map_status(raw: Optional[str]) -> str:
    return _STATUS_MAP.get((raw or "OPEN").upper(), OPEN)


def is_unresolved(raw: Optional[str]) -> bool:
    return map_status(raw) in (OPEN, ACKNOWLEDGED)


# ---------- no false all-clear ----------
_SUBJECT = (r"(?:interlocks?|alerts?|alarms?|conflicts?|hazards?|issues?|isolations?|bypass(?:es)?|permits?|"
            r"situations?|risks?|concerns?|detectors?|gas|plant|area|system|everything)")
_CLEARED = r"(?:clear(?:ed)?|resolved|mitigated|closed out)"
_PATTERNS = [
    re.compile(r"\ball[- ]clear\b", re.I),
    re.compile(rf"\b{_SUBJECT}\s+(?:is |are |was |were |has been |have been |now |remains? |already |fully |safely )*(?:\w+\s+){{0,2}}?{_CLEARED}\b", re.I),
    re.compile(r"\b(?:has|have|had|been) (?:been )?(?:cleared|resolved|mitigated)\b", re.I),
    # assertions of state: "is resolved", "was mitigated", "already cleared" ...
    re.compile(r"\b(?:is|are|was|were|been|now|already|successfully|fully)\s+(?:\w+\s+)?(?:resolved|mitigated|cleared)\b", re.I),
    # a clause that is just the claim: "Resolved." / "Mitigated."
    re.compile(r"(?:^|[.;:!?\n]\s*)(?:resolved|mitigated|cleared)\b", re.I),
    re.compile(r"\bsafe to (?:proceed|start|restart|resume|operate|begin|continue|commence)\b", re.I),
    re.compile(r"\bsafely (?:proceed|resume|start|restart)\b", re.I),
    re.compile(r"\bno (?:further |immediate |additional )?(?:action|concerns?|issues?|hazards?|risks?)(?: is| are)? (?:required|needed|remain|present|identified)\b", re.I),
    re.compile(r"\bnothing to (?:worry|report|action)\b", re.I),
    re.compile(r"\b(?:everything|all|situation) (?:is|looks|appears|seems) (?:normal|fine|good|ok(?:ay)?|safe|secure|under control)\b", re.I),
]
# A match is fine when it is negated just before: "not yet resolved", "until mitigated", "cannot proceed".
_NEGATION = re.compile(r"(?:\bnot\b|\bno\b|\bnever\b|n't\b|\buntil\b|\bunless\b|\bbefore\b|\bwithout\b|\byet to be\b|\bcannot\b|\bonly when\b|\bonce\b|\bif\b|\bwhether\b|\bto be\b|\bmust be\b|\bnot be\b|\bpending\b|\bawaiting\b|\bprior to\b|\bonly after\b|\bonce\b)", re.I)
_NEGATION_WINDOW = 200   # look back through the whole clause, not a few characters


def find_clearing_language(text: str, context: int = 0) -> list[str]:
    """Return the assertive 'it is fine' phrases found in text (empty if none).
    With context > 0 each phrase comes with that many characters of surrounding text."""
    found = []
    for pat in _PATTERNS:
        for m in pat.finditer(text or ""):
            before = text[max(0, m.start() - _NEGATION_WINDOW):m.start()]
            # only look at the current clause
            before = re.split(r"[.;:!?\n]", before)[-1]
            inner = re.sub(r"^(?:no|nothing)\b", "", m.group(0), flags=re.I)  # 'no action required' is itself the claim
            if _NEGATION.search(before) or _NEGATION.search(inner):
                continue
            found.append(text[max(0, m.start() - context):m.end() + context].strip() if context else m.group(0).strip())
    return list(dict.fromkeys(found))


def check_no_false_all_clear(texts: Iterable[str], unresolved_conflicts: bool) -> list[str]:
    """Violations when any conflict is open or only acknowledged and the text says otherwise."""
    if not unresolved_conflicts:
        return []
    out = []
    for t in texts:
        out += [f"clearing language: '{p}'" for p in find_clearing_language(t, context=40)]
    return list(dict.fromkeys(out))


# ---------- verdict lock ----------
def check_verdict_lock(items: list, verdicts: list[RuleVerdict]) -> list[str]:
    """Every rule verdict must appear with the same rule ID and a severity at least as high."""
    problems = []
    for v in verdicts:
        match = [i for i in items if getattr(i, "verdict_id", None) == v.verdict_id
                 or (getattr(i, "rule_id", None) == v.rule_id and getattr(i, "asset_tag", None) == v.asset_tag)]
        if not match:
            problems.append(f"verdict {v.rule_id} ({v.verdict_id}) is missing")
            continue
        if not any(SEVERITY_RANK[i.severity] >= SEVERITY_RANK[v.severity] for i in match):
            problems.append(f"verdict {v.rule_id} ({v.verdict_id}) was downgraded below {v.severity}")
        if any(getattr(i, "rule_id", None) not in (None, v.rule_id) and getattr(i, "verdict_id", None) == v.verdict_id for i in match):
            problems.append(f"verdict {v.rule_id} ({v.verdict_id}) was relabelled")
    return problems


# ---------- citations ----------
def strip_unretrieved(citations: list[str], retrieved_ids: set[str]) -> tuple[list[str], list[str]]:
    kept = [c for c in citations if c in retrieved_ids]
    removed = [c for c in citations if c not in retrieved_ids]
    return kept, removed


def clamp_advisory_severity(items: list) -> list[str]:
    """Advisory items cannot be CRITICAL: only the rules raise critical alerts."""
    changed = []
    for i in items:
        if getattr(i, "source", "rule") == "advisory" and i.severity == "CRITICAL":
            i.severity = "WARNING"
            changed.append("advisory item capped at WARNING")
    return changed


@dataclass
class GuardrailLog:
    """Collects triggers for the trace and the stored brief."""
    triggers: list[dict] = field(default_factory=list)

    def add(self, agent: str, name: str, detail: str) -> None:
        self.triggers.append({"agent": agent, "guardrail": name, "detail": detail[:200]})

    @property
    def names(self) -> list[str]:
        return sorted({t["guardrail"] for t in self.triggers})
