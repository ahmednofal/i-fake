"""Google Gemini provider — uses the free Gemini 2.0 Flash model by default."""

from __future__ import annotations

import asyncio
import json
import re

from google import genai
from google.genai import types

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

log = get_logger("i_fake.ai.gemini")


def _extract_json(text: str) -> str:
    """
    Robustly pull the first complete JSON object or array out of *text*,
    regardless of surrounding prose or markdown code fences.
    """
    # Try to find a JSON object {...} or array [...]
    for start_char, end_char in (("{" , "}"), ("[", "]")):
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    raise ValueError(f"No JSON object/array found in response: {text[:200]!r}")


class GeminiProvider(AIProvider):
    """
    Google Gemini provider.
    Default model: gemini-2.0-flash  (free tier via Google AI Studio).
    Get a free API key at https://aistudio.google.com/app/apikey
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def _chat(
        self,
        system: str,
        user: str,
        temperature: float = 1.0,
        max_tokens: int = 900,
    ) -> str:
        last_exc: Exception | None = None
        for attempt in range(3):
            if attempt:
                wait = 3.0 * attempt
                log.warning("Retrying Gemini call in %.0fs (attempt %d/3) …", wait, attempt + 1)
                await asyncio.sleep(wait)
            try:
                resp = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                    ),
                )
            except Exception as exc:
                msg = str(exc)
                if "RESOURCE_EXHAUSTED" in msg and "limit: 0" in msg:
                    raise RuntimeError(
                        "\n[Gemini quota] Your API key has free-tier limit = 0.\n"
                        "This usually means the key is from a Google Cloud project, "
                        "not AI Studio.\n"
                        "➜  Get a free AI Studio key at: "
                        "https://aistudio.google.com/app/apikey\n"
                        "Then update IFAKE_GEMINI_API_KEY in your .env file."
                    ) from None
                raise
            raw = resp.text or ""
            # Log why Gemini stopped generating (helps diagnose truncation)
            try:
                reason = resp.candidates[0].finish_reason
                if reason and str(reason) not in ("FinishReason.STOP", "1", "STOP"):
                    log.warning("Gemini finish_reason=%s on attempt %d", reason, attempt + 1)
            except Exception:
                pass
            try:
                extracted = _extract_json(raw)
                json.loads(extracted)  # full parse validation — catches syntactically broken JSON
                return extracted
            except (ValueError, json.JSONDecodeError) as exc:
                log.warning(
                    "Truncated/unparseable response on attempt %d/3 (%d chars): %s",
                    attempt + 1, len(raw), exc,
                )
                last_exc = exc
        raise RuntimeError(
            f"Gemini returned unparseable JSON after 3 attempts."
        ) from last_exc

    async def generate_persona(self, constraints: str = "", existing_names: list[str] | None = None) -> Persona:
        log.debug("Requesting persona from Gemini (%s) …", self._model)
        raw = await self._chat(PERSONA_SYSTEM, persona_user_prompt(constraints, existing_names), max_tokens=1500)
        return Persona(**json.loads(raw))

    async def plan_session(self, persona: Persona, recent_themes: list[str] | None = None) -> BrowsingPlan:
        log.debug("Requesting session plan from Gemini for persona %s …", persona.id[:8])
        raw = await self._chat(
            PLAN_SYSTEM,
            plan_user_prompt(_persona_summary(persona), recent_themes),
            temperature=0.9,
            max_tokens=4096,
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
