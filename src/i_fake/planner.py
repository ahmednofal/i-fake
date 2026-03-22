"""Session planner — uses the AI provider to produce BrowsingPlans."""

from __future__ import annotations

from .ai.provider import AIProvider
from .config import Settings
from .models import BrowsingPlan, Persona
from .utils.logger import get_logger

log = get_logger("i_fake.planner")


class SessionPlanner:
    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self._ai = provider
        self._sessions_dir = settings.data_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        # Track recent themes per persona to avoid repetition
        self._recent_themes: dict[str, list[str]] = {}

    async def create_plan(self, persona: Persona) -> BrowsingPlan:
        log.info(
            "Planning session for persona %s (%s) …", persona.id[:8], persona.name
        )
        recent = self._recent_themes.get(persona.id, [])
        plan = await self._ai.plan_session(persona, recent_themes=recent)
        # Record this theme so next plan avoids it
        themes = self._recent_themes.setdefault(persona.id, [])
        themes.append(plan.session_theme)
        if len(themes) > 12:
            themes.pop(0)
        self._save(plan)
        log.info(
            "Plan %s ready: '%s' — %d actions (~%.1f min)",
            plan.id[:8],
            plan.session_theme,
            len(plan.actions),
            plan.estimated_duration_minutes,
        )
        return plan

    def _save(self, plan: BrowsingPlan) -> None:
        path = self._sessions_dir / f"plan_{plan.id}.json"
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def load(self, plan_id: str) -> BrowsingPlan:
        path = self._sessions_dir / f"plan_{plan_id}.json"
        return BrowsingPlan.model_validate_json(path.read_text(encoding="utf-8"))
