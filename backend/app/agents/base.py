"""Agent base classes.

Agents are workflow stages: deterministic graph algorithms DECIDE, the LLM
(mock by default) only WRITES structured rationale text from the supplied
facts. Agents never invent facts: every claim must reference an Evidence item
built from tool output.
"""
from __future__ import annotations

import dataclasses
import typing

from backend.app.llm.provider import LLMProvider
from backend.app.tools.base import ToolRegistry


@dataclasses.dataclass
class AgentContext:
    db: typing.Any                      # SQLAlchemy Session
    llm: LLMProvider
    tools: ToolRegistry
    graph: typing.Any                   # DependencyGraph
    analysis_id: int
    transport: typing.Any               # models.Transport
    seeds: list                         # [(node_key, value_affecting)]
    closure: dict                       # impacted_closure result
    settings: typing.Any = None


@dataclasses.dataclass
class StageOutput:
    output: dict                        # structured stage payload
    evidence: list[Evidence]            # noqa: F821 - filled via make_evidence
    hypotheses: list[dict]
    actions: list[dict]
    decision: dict

    @staticmethod
    def empty() -> "StageOutput":
        return StageOutput(output={}, evidence=[], hypotheses=[], actions=[], decision={})


def make_evidence(source: str, fact: str, reliability: float = 0.95,
                  raw_reference: str = "") -> dict:
    """Build an evidence dict conforming to app.schemas.Evidence."""
    return {
        "source": source,
        "fact": fact,
        "reliability": reliability,
        "raw_reference": raw_reference,
    }


class BaseAgent:
    name: str = "base"
    description: str = ""

    def run(self, ctx: AgentContext) -> StageOutput:
        raise NotImplementedError

    # shared helper: ask the LLM (mock) to phrase a rationale from facts only
    def rationale(self, ctx: AgentContext, stage_facts: dict) -> str:
        import json

        from backend.app.llm.provider import FACTS_MARKER

        prompt = (
            f"You are the {self.name}. Using ONLY the facts provided, write a "
            f"concise audit-ready rationale. Do not invent anything.\n"
            f"{FACTS_MARKER}{json.dumps(stage_facts, default=str)}"
        )
        raw = ctx.llm.complete(prompt, system="Facts-only mode.", json_mode=True)
        try:
            import json as _json
            parsed = _json.loads(raw)
            return str(parsed.get("summary", raw))
        except Exception:
            return str(raw)
