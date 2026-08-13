"""Model Provider — unified external-LLM interface (§25, §26).

The engine never calls a raw LLM directly. Agents at AI level >= 2 ask the
provider for a *structured decision*, which the engine validates before
applying (§27) — so a hallucinating model cannot break simulation rules.

Providers:
    RuleBasedProvider        — deterministic fallback, no network (default).
    OpenAICompatibleProvider — any OpenAI-style HTTP endpoint (Ollama, vLLM,
                               DeepSeek, local LLM, …).
"""

from __future__ import annotations

import json
import random
import re
import urllib.request
from typing import Optional


class ModelProvider:
    name = "base"

    def chat(self, model: str, messages: list, temperature: float = 0.7) -> dict:
        raise NotImplementedError

    def decide(self, agent_snapshot: dict, context: str) -> dict:
        """Ask the model for a structured decision for one agent."""
        raise NotImplementedError


class RuleBasedProvider(ModelProvider):
    """Deterministic decision maker — used for the vast majority of agents."""

    name = "rule_based"

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng or random.Random()

    def chat(self, model: str, messages: list, temperature: float = 0.7) -> dict:
        return {"content": "[rule-based provider: no LLM configured]", "usage": {}}

    def decide(self, agent_snapshot: dict, context: str) -> dict:
        # Simple heuristic: trade if rich, seek resources if poor.
        money = agent_snapshot.get("resources", {}).get("money", 0.0)
        food = agent_snapshot.get("resources", {}).get("food", 0.0)
        if food < 20 or money < 15:
            return {
                "action": "seek_resources",
                "target": None,
                "amount": 0,
                "reason": "survival pressure",
                "confidence": 0.9,
            }
        if money > 500:
            return {
                "action": "trade",
                "target": None,
                "amount": self._rng.randint(5, 30),
                "reason": "surplus capital",
                "confidence": 0.7,
            }
        return {"action": "produce", "target": None, "amount": 0, "reason": "normal work", "confidence": 0.8}


class OpenAICompatibleProvider(ModelProvider):
    """Calls any OpenAI-compatible /chat/completions endpoint."""

    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, model: str, messages: list, temperature: float = 0.7) -> dict:
        payload = json.dumps(
            {"model": model, "messages": messages, "temperature": temperature}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return {"content": content, "usage": data.get("usage", {})}

    def decide(self, agent_snapshot: dict, context: str) -> dict:
        system = (
            "You are the decision core of one agent in a social simulation. "
            "Reply with ONLY a JSON object with keys: action, target, amount, reason, confidence. "
            "Allowed actions: produce, trade, seek_resources, express_discontent, form_alliance, rest."
        )
        user = f"Agent state:\n{json.dumps(agent_snapshot, ensure_ascii=False)}\nContext:\n{context}"
        result = self.chat("", [{"role": "system", "content": system}, {"role": "user", "content": user}])
        text = result.get("content", "")
        try:
            # Tolerate markdown fences around JSON.
            m = re.search(r"\{.*\}", text, re.DOTALL)
            decision = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            decision = {}
        return {
            "action": decision.get("action", "rest"),
            "target": decision.get("target"),
            "amount": decision.get("amount", 0),
            "reason": decision.get("reason", ""),
            "confidence": decision.get("confidence", 0.5),
        }


def make_provider(cfg: dict) -> ModelProvider:
    """Build a provider from the `model` section of config."""
    model_cfg = cfg.get("model", {})
    provider = model_cfg.get("provider", "rule_based")
    if provider in ("openai", "openai_compatible", "ollama", "compatible"):
        base_url = model_cfg.get("base_url", "http://127.0.0.1:11434/v1")
        return OpenAICompatibleProvider(base_url, model_cfg.get("api_key", ""))
    return RuleBasedProvider()
