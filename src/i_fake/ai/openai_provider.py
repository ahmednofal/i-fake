"""OpenAI provider implementation."""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from ..models import BrowsingAction, BrowsingPlan, Persona
from ..utils.logger import get_logger
from .prompts import (
    PERSONA_SYSTEM,
    PLAN_SYSTEM,
    QUERY_SYSTEM,
    persona_user_prompt,
    plan_user_prompt,
    query_user_prompt,
)
from .provider import AIProvider

log = get_logger("i_fake.ai.openai")


def _persona_summary(persona: Persona) -> str:
    return (
        f"Name: {persona.name}, age {persona.age_range.value}, "
        f"{persona.gender.value}, occupation: {persona.occupation}, "
        f"location: {persona.location}.\n"
        f"Interests: {', '.join(persona.interests)}.\n"
        f"Shopping: {', '.join(persona.shopping_categories)}.\n"
        f"Favourite sites: {', '.join(persona.favorite_sites)}.\n"
        f"Search style: {persona.search_style}.\n"
        f"Notes: {persona.personality_notes}"
    )


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate_persona(self, constraints: str = "", existing_names: list[str] | None = None) -> Persona:
        log.debug("Requesting persona from OpenAI (%s) …", self._model)
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": PERSONA_SYSTEM},
                {"role": "user", "content": persona_user_prompt(constraints, existing_names)},
            ],
            temperature=1.1,
            max_tokens=900,
        )
        raw = resp.choices[0].message.content or ""
        return Persona(**json.loads(raw))

    async def plan_session(self, persona: Persona, recent_themes: list[str] | None = None) -> BrowsingPlan:
        log.debug("Requesting session plan from OpenAI for persona %s …", persona.id[:8])
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": plan_user_prompt(_persona_summary(persona), recent_themes, persona.activity_log or None)},
            ],
            temperature=0.9,
            max_tokens=1400,
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(raw)
        actions = [BrowsingAction(**a) for a in data.pop("actions")]
        return BrowsingPlan(persona_id=persona.id, actions=actions, **data)

    async def generate_search_queries(
        self, persona: Persona, topic: str, n: int = 5
    ) -> list[str]:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": QUERY_SYSTEM},
                {"role": "user", "content": query_user_prompt(_persona_summary(persona), topic, n)},
            ],
            temperature=0.95,
            max_tokens=400,
        )
        return json.loads(resp.choices[0].message.content or "[]")
