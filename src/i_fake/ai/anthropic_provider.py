"""Anthropic (Claude) provider implementation."""

from __future__ import annotations

import json

import anthropic

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

log = get_logger("i_fake.ai.anthropic")


class AnthropicProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate_persona(self, constraints: str = "", existing_names: list[str] | None = None) -> Persona:
        log.debug("Requesting persona from Anthropic (%s) …", self._model)
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=900,
            system=PERSONA_SYSTEM,
            messages=[{"role": "user", "content": persona_user_prompt(constraints)}],
        )
        raw = msg.content[0].text
        return Persona(**json.loads(raw))

    async def plan_session(self, persona: Persona, recent_themes: list[str] | None = None) -> BrowsingPlan:
        log.debug("Requesting session plan from Anthropic for persona %s …", persona.id[:8])
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=1400,
            system=PLAN_SYSTEM,
            messages=[
                {"role": "user", "content": plan_user_prompt(_persona_summary(persona), recent_themes)}
            ],
        )
        raw = msg.content[0].text
        data = json.loads(raw)
        actions = [BrowsingAction(**a) for a in data.pop("actions")]
        return BrowsingPlan(persona_id=persona.id, actions=actions, **data)

    async def generate_search_queries(
        self, persona: Persona, topic: str, n: int = 5
    ) -> list[str]:
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=400,
            system=QUERY_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": query_user_prompt(_persona_summary(persona), topic, n),
                }
            ],
        )
        return json.loads(msg.content[0].text)
