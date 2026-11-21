"""LLM provider protocol + implementations.

The platform runs fully on MockLLMProvider: a deterministic generator that
writes structured rationales STRICTLY from the facts embedded in the prompt.
No network access happens in mock mode. OpenAICompatibleProvider exists for
future real integration behind the same Protocol.
"""
from __future__ import annotations

import json
import re
import time
from typing import Protocol

from backend.app import metrics
from backend.app.config import Settings

FACTS_MARKER = "FACTS_JSON:"


class LLMProvider(Protocol):
    mode: str

    def complete(self, prompt: str, *, system: str = "", json_mode: bool = False) -> str:
        ...


def _extract_facts(prompt: str) -> dict:
    if FACTS_MARKER in prompt:
        raw = prompt.split(FACTS_MARKER, 1)[1].strip()
        try:
            parsed = json.loads(raw.split("\n```")[0].strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


class MockLLMProvider:
    """Deterministic, facts-only rationale writer. mode='mock'.

    It renders sentences exclusively from the JSON facts block of the prompt;
    identical prompts always yield identical output (verified by tests).
    """

    mode = "mock"

    def complete(self, prompt: str, *, system: str = "", json_mode: bool = False) -> str:
        t0 = time.perf_counter()
        facts = _extract_facts(prompt)
        text = self._render(facts)
        metrics.observe_llm(self.mode, time.perf_counter() - t0)
        return json.dumps({"summary": text, "confidence": 0.95, "mode": "mock"})

    @staticmethod
    def _render(facts: dict) -> str:
        parts: list[str] = []
        stage = str(facts.get("stage", "analysis"))
        parts.append(f"{stage} completed using deterministic graph analysis over the simulated SAP-like estate.")
        changed = facts.get("changed_objects") or []
        if changed:
            keys = ", ".join(str(c) for c in changed[:6])
            more = f" (+{len(changed) - 6} more)" if len(changed) > 6 else ""
            parts.append(f"Changed objects under review: {keys}{more}.")
        impacted = facts.get("impacted_processes") or []
        if impacted:
            names = ", ".join(sorted(str(p) for p in impacted))
            parts.append(f"Impacted business processes derived from the dependency closure: {names}.")
        interfaces = facts.get("impacted_interfaces") or []
        if interfaces:
            parts.append(
                "Interfaces inside the impact radius: "
                + ", ".join(sorted(str(i) for i in interfaces))
                + ". Partner systems must be notified before release."
            )
        tests = facts.get("selected_tests") or []
        if tests:
            parts.append(
                f"{len(tests)} regression tests selected out of "
                f"{facts.get('total_tests', '?')} total; scope is intentionally minimal, not rerun-everything."
            )
        excluded = facts.get("excluded_tests")
        if isinstance(excluded, int):
            parts.append(f"{excluded} tests excluded as unaffected by the dependency graph.")
        risk = facts.get("risk_band")
        if risk:
            score = facts.get("risk_score")
            factors = facts.get("top_risk_factors") or []
            ftxt = (" Leading factors: " + "; ".join(str(f) for f in factors)) if factors else ""
            parts.append(f"Computed release risk {score}/100 ({risk}).{ftxt}")
        checks = facts.get("validation_checks") or []
        if checks:
            ok = sum(1 for c in checks if c.get("status") == "PASS")
            parts.append(f"Pre-release checks: {ok}/{len(checks)} passed.")
        findings = facts.get("findings") or []
        for f in findings[:4]:
            parts.append(str(f))
        if len(parts) == 2:
            parts.append("No additional impact signals found in the supplied facts.")
        return " ".join(parts)


class OpenAICompatibleProvider:
    """Thin httpx client for any OpenAI-compatible /chat/completions endpoint.

    Real integration point: point LLM_BASE_URL at a gateway serving e.g. Azure
    Grok/GPT models. The agent workflow passes only verified facts in the
    system prompt and demands JSON output.
    """

    mode = "openai"

    def __init__(self, settings: Settings) -> None:
        import httpx  # local import keeps mock mode dependency-light at runtime

        self._settings = settings
        self._httpx = httpx

    def complete(self, prompt: str, *, system: str = "", json_mode: bool = False) -> str:
        t0 = time.perf_counter()
        headers = {"Authorization": f"Bearer {self._settings.LLM_API_KEY}"}
        payload = {
            "model": self._settings.LLM_MODEL,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        url = self._settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
        with self._httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        metrics.observe_llm(self.mode, time.perf_counter() - t0)
        content = data["choices"][0]["message"]["content"]
        # strip accidental markdown fences
        return re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings_safe()
    if settings.LLM_MODE.lower() == "openai":
        return OpenAICompatibleProvider(settings)
    return MockLLMProvider()


def get_settings_safe():
    from backend.app.config import get_settings

    return get_settings()
