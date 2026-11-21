"""Tool registry: ToolSpec + audited execution.

Agents act through registered tools; every invocation is persisted to the
tool_calls table (audit trail) and observed in Prometheus. No shell/network
tools exist in this registry by design.
"""
from __future__ import annotations

import json
import logging
import time
import typing

from sqlalchemy.orm import Session

from backend.app import metrics
from backend.app.models import ToolCallRow

logger = logging.getLogger(__name__)


class ToolError(Exception):
    pass


class UnknownToolError(ToolError):
    pass


class ToolSpec(typing.NamedTuple):
    name: str
    description: str
    input_schema: dict           # simple JSON-schema-ish descriptor
    handler: typing.Callable     # (payload: dict, ctx: dict) -> dict


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise UnknownToolError(f"unknown tool: {name}")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    def execute(
        self,
        name: str,
        payload: dict | None,
        *,
        session: Session,
        analysis_id: int = 0,
        audit: bool = True,
    ) -> dict:
        spec = self.get(name)
        payload = payload or {}
        # basic schema validation: required keys
        required = spec.input_schema.get("required", [])
        missing = [k for k in required if k not in payload]
        if missing:
            raise ToolError(f"tool {name} missing required input keys: {missing}")
        t0 = time.perf_counter()
        ok = True
        try:
            result = spec.handler(payload)
            result = result if isinstance(result, dict) else {"result": result}
        except Exception as exc:  # noqa: BLE001 - tool boundary
            ok = False
            logger.warning("tool %s failed: %s", name, exc)
            result = {"error": str(exc)}
            raise
        finally:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            metrics.observe_tool(name, duration_ms / 1000.0)
            if audit:
                safe_out = _safe_json(result)
                db_row = ToolCallRow(
                    tool=name,
                    input_json=_safe_json(payload),
                    output_json=safe_out,
                    ok=ok,
                    duration_ms=duration_ms,
                    analysis_id=analysis_id or 0,
                )
                try:
                    session.add(db_row)
                    session.commit()
                except Exception:  # pragma: no cover - audit must not break flow
                    session.rollback()
        return result


def _safe_json(obj) -> dict:
    try:
        json.dumps(obj)
        return obj if isinstance(obj, dict) else {"value": obj}
    except Exception:
        return {"repr": repr(obj)[:500]}
