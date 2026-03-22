"""Abstract base class that all AI provider implementations must satisfy."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import BrowsingPlan, Persona


class AIProvider(ABC):
    """Common interface for AI backends (OpenAI, Anthropic, local models)."""

    @abstractmethod
    async def generate_persona(self, constraints: str = "", existing_names: list[str] | None = None) -> Persona:
        """Generate and return a fresh fake persona.

        Args:
            constraints: Optional demographic constraints, e.g.
                "Arab Egyptian Muslim male, 30 years old, Cairo".
            existing_names: Names of already-existing personas so the AI
                can avoid generating duplicates.
        """

    @abstractmethod
    async def plan_session(self, persona: Persona, recent_themes: list[str] | None = None) -> BrowsingPlan:
        """Return a realistic browsing session plan for *persona*."""

    @abstractmethod
    async def generate_search_queries(
        self, persona: Persona, topic: str, n: int = 5
    ) -> list[str]:
        """Return *n* realistic search queries this persona would type."""
