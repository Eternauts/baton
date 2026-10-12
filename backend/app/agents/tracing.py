"""Trace collector: an ADK plugin that records every agent, tool and model step to
agent_runs/{run_id}/steps. Writes are batched and never fail the run."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from google.adk.plugins import BasePlugin

from app.knowledge.store import get_db

logger = logging.getLogger("baton.agents.trace")
_INTERNAL_TOOLS = {"set_model_response"}   # ADK's own structured-output tool; not interesting to show
_FLUSH_AT = 6


def _short(value: Any, n: int = 80) -> str:
    s = str(value).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


class TraceCollector(BasePlugin):
    def __init__(self, run_ctx, write: bool = True):
        super().__init__(name="baton_trace")
        self.ctx = run_ctx
        self.write = write
        self.steps: list[dict] = []          # everything, in order (also used by tests)
        self._pending: list[dict] = []
        self._seq = 0
        self._starts: dict[Any, float] = {}
        self._lock = asyncio.Lock()
        run_ctx.trace = self

    # ---- recording ----
    def add_step(self, kind: str, agent: str, summary: str, tool_name: Optional[str] = None,
                 retrieved_ids: Optional[list] = None, rule_ids: Optional[list] = None,
                 latency_ms: Optional[int] = None) -> None:
        self._seq += 1
        step = {"seq": self._seq, "agent": agent, "kind": kind, "tool_name": tool_name, "summary": summary[:200],
                "retrieved_ids": retrieved_ids or [], "rule_ids": rule_ids or [], "latency_ms": latency_ms,
                "timestamp": datetime.now(timezone.utc)}
        self.steps.append(step)
        self._pending.append(step)

    def _lat(self, key) -> Optional[int]:
        t = self._starts.pop(key, None)
        return int((time.time() - t) * 1000) if t else None

    # ---- ADK hooks ----
    async def before_agent_callback(self, *, agent, callback_context):
        self._starts[("agent", agent.name)] = time.time()
        self.add_step("agent_start", agent.name, f"{agent.name} started")

    async def after_agent_callback(self, *, agent, callback_context):
        self.add_step("agent_end", agent.name, f"{agent.name} finished", latency_ms=self._lat(("agent", agent.name)))
        await self.flush()

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        if tool.name in _INTERNAL_TOOLS:
            return None
        self._starts[("tool", tool_context.agent_name, tool.name)] = time.time()
        q = tool_args.get("query") or tool_args.get("asset_tags") or tool_args.get("handover_id") or tool_args.get("unit") or ""
        self.add_step("tool_call", tool_context.agent_name, f"{tool.name}({_short(q)})", tool_name=tool.name)
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        if tool.name in _INTERNAL_TOOLS:
            return None
        res = result if isinstance(result, dict) else {}
        ids = [h.get("chunk_id") for h in res.get("hits", []) if isinstance(h, dict)]
        rules = [v.get("rule_id") for v in res.get("verdicts", []) if isinstance(v, dict)]
        self.add_step("tool_result", tool_context.agent_name, f"{tool.name} returned {len(res['hits']) if 'hits' in res else len(rules) if 'verdicts' in res else len(res)} item(s)",
                      tool_name=tool.name, retrieved_ids=ids, rule_ids=rules,
                      latency_ms=self._lat(("tool", tool_context.agent_name, tool.name)))
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        u = getattr(llm_response, "usage_metadata", None)
        if u is not None:
            tin, tout = (u.prompt_token_count or 0), ((u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0))
            t = self.ctx.tokens.setdefault(callback_context.agent_name, [0, 0])
            t[0] += tin
            t[1] += tout
            self.add_step("model_output", callback_context.agent_name, f"model call: {tin} in / {tout} out tokens")
        return None

    # ---- persistence ----
    async def flush(self) -> None:
        if not self.write or not self._pending:
            return
        async with self._lock:
            batch, self._pending = self._pending, []
            try:
                await asyncio.to_thread(self._write, batch)
            except Exception as err:  # noqa: BLE001 - tracing must never fail the run
                logger.warning("trace write failed (%d steps): %s", len(batch), type(err).__name__)

    def _write(self, batch: list[dict]) -> None:
        db = get_db()
        wb = db.batch()
        col = db.collection("agent_runs").document(self.ctx.run_id).collection("steps")
        for s in batch:
            wb.set(col.document(f"{s['seq']:04d}"), s)
        wb.commit()
