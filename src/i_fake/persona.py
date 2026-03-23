"""Persona filesystem store — load, save, rotate, and select personas."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import Settings
from .models import Persona
from .utils.logger import get_logger

log = get_logger("i_fake.persona")


class PersonaStore:
    """Manages persona JSON files under ``settings.personas_dir``."""

    def __init__(self, settings: Settings) -> None:
        self._dir = settings.personas_dir
        self._rotation_days = settings.persona_rotation_days
        self._max_active = settings.max_active_personas
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, persona: Persona) -> Path:
        path = self._dir / f"{persona.id}.json"
        path.write_text(persona.model_dump_json(indent=2), encoding="utf-8")
        log.debug("Saved persona %s (%s) → %s", persona.id[:8], persona.name, path)
        return path

    def load(self, persona_id: str) -> Persona:
        return Persona.model_validate_json(
            (self._dir / f"{persona_id}.json").read_text(encoding="utf-8")
        )

    def load_all(self) -> list[Persona]:
        personas: list[Persona] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                personas.append(Persona.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception as exc:
                log.warning("Skipping invalid persona file %s: %s", path.name, exc)
        return personas

    def delete(self, persona_id: str) -> None:
        (self._dir / f"{persona_id}.json").unlink(missing_ok=True)
        log.info("Deleted persona %s", persona_id[:8])

    # ── Selection ──────────────────────────────────────────────────────────────

    def active_personas(self) -> list[Persona]:
        return [p for p in self.load_all() if p.active]

    def pick_for_session(self) -> Optional[Persona]:
        """Return the least-recently-used active persona (LRU scheduler)."""
        actives = self.active_personas()
        if not actives:
            return None
        return sorted(actives, key=lambda p: p.last_used or datetime.min)[0]

    def mark_used(self, persona_id: str) -> None:
        persona = self.load(persona_id)
        persona.last_used = datetime.utcnow()
        self.save(persona)

    def append_activity(self, persona_id: str, summary: str, max_entries: int = 30) -> None:
        """Append a one-line session summary to the persona's activity log."""
        persona = self.load(persona_id)
        persona.activity_log.append(summary)
        if len(persona.activity_log) > max_entries:
            persona.activity_log = persona.activity_log[-max_entries:]
        self.save(persona)
        log.debug("Activity logged for %s: %s", persona_id[:8], summary)

    # ── Rotation ───────────────────────────────────────────────────────────────

    def rotate_old(self) -> list[str]:
        """
        Deactivate personas older than ``rotation_days``.
        Returns list of deactivated persona IDs.
        """
        cutoff = datetime.utcnow() - timedelta(days=self._rotation_days)
        retired: list[str] = []
        for persona in self.active_personas():
            if persona.created_at < cutoff:
                persona.active = False
                self.save(persona)
                retired.append(persona.id)
                log.info(
                    "Retired persona %s (%s) — exceeded %d-day rotation window",
                    persona.id[:8],
                    persona.name,
                    self._rotation_days,
                )
        return retired
