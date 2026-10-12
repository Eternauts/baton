"""Per-run state shared by tools, guard wrappers and the trace collector (plain Python, one per pipeline run)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.guardrails import GuardrailLog
from app.agents.schemas import RuleVerdict


@dataclass
class RunContext:
    run_id: str
    trigger: str
    handover_id: Optional[str]
    unit: Optional[str]
    capsules: list[dict] = field(default_factory=list)
    verdicts: list[RuleVerdict] = field(default_factory=list)
    unresolved_elsewhere: bool = False        # unresolved conflicts for the unit from other recent handovers
    retrieved: dict[str, dict] = field(default_factory=dict)   # chunk_id -> compact hit, filled by the search tools
    guard: GuardrailLog = field(default_factory=GuardrailLog)
    trace: Any = None                          # TraceCollector
    models_used: set = field(default_factory=set)
    tokens: dict[str, list[int]] = field(default_factory=dict)  # agent -> [prompt, output]
    fallback_agents: list[str] = field(default_factory=list)
    llm_agents: list = field(default_factory=list)   # LlmAgents of this run, so their model clients can be closed

    @property
    def retrieved_ids(self) -> set[str]:
        return set(self.retrieved)

    @property
    def has_unresolved(self) -> bool:
        """True if this handover raised any rule verdict, or the unit has other unresolved conflicts."""
        return bool(self.verdicts) or self.unresolved_elsewhere

    def step(self, kind: str, agent: str, summary: str, **kw) -> None:
        if self.trace is not None:
            self.trace.add_step(kind, agent, summary, **kw)
