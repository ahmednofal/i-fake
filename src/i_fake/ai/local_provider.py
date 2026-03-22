"""
Local model provider — talks to any OpenAI-compatible endpoint.
Works with Ollama, llama.cpp server, LM Studio, etc.

Switch from an online provider to this one by setting:
    IFAKE_AI_PROVIDER=local
    IFAKE_LOCAL_MODEL_URL=http://localhost:11434/v1
    IFAKE_LOCAL_MODEL_NAME=llama3
"""

from __future__ import annotations

import json

import httpx

from ..models import BrowsingAction, BrowsingPlan, Persona
from ..utils.logger import get_logger
from .openai_provider import _persona_summary
from .prompts import (
    PERSONA_SYSTEM,
    PLAN_SYSTEM,
    QUERY_SYSTEM,
    persona_user_prompt,
    plan_user_prompt,
    query_user_prompt,
)
from .provider import AIProvider

log = get_logger("i_fake.ai.local")


class LocalProvider(AIProvider):
    """
    OpenAI-compatible local model provider.
    Privacy advantage: the model never sees real traffic — no telemetry leaks.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3",
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def _chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 900,
        temperature: float = 0.9,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        resp = await self._http.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def generate_persona(self, constraints: str = "", existing_names: list[str] | None = None) -> Persona:
        log.debug("Requesting persona from local model '%s' …", self._model)
        raw = await self._chat(PERSONA_SYSTEM, persona_user_prompt(constraints, existing_names))
        return Persona(**json.loads(raw))

    async def plan_session(self, persona: Persona, recent_themes: list[str] | None = None) -> BrowsingPlan:
        log.debug("Requesting session plan from local model for persona %s …", persona.id[:8])
        raw = await self._chat(
            PLAN_SYSTEM,
            plan_user_prompt(_persona_summary(persona), recent_themes),
            max_tokens=1400,
        )
        data = json.loads(raw)
        actions = [BrowsingAction(**a) for a in data.pop("actions")]
        return BrowsingPlan(persona_id=persona.id, actions=actions, **data)

    async def generate_search_queries(
        self, persona: Persona, topic: str, n: int = 5
    ) -> list[str]:
        raw = await self._chat(
            QUERY_SYSTEM,
            query_user_prompt(_persona_summary(persona), topic, n),
            max_tokens=400,
        )
        return json.loads(raw)

    async def aclose(self) -> None:
        await self._http.aclose()
