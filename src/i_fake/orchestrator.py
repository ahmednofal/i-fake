"""
Orchestrator — ties together personas, planning, and browser execution.
Also owns the APScheduler background scheduler for unattended operation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .ai.provider import AIProvider
from .browser import BrowserController
from .config import Settings
from .models import SessionRecord, SessionStatus
from .persona import PersonaStore
from .planner import SessionPlanner
from .utils.logger import get_logger

log = get_logger("i_fake.orchestrator")


class Orchestrator:
    """
    High-level coordinator for fake-traffic sessions.

    Usage (single run)::

        orch = Orchestrator(settings, provider)
        record = await orch.run_session()

    Usage (scheduled)::

        orch.start_scheduler()
        # ... keep event loop alive ...
        orch.stop_scheduler()
    """

    def __init__(self, settings: Settings, ai_provider: AIProvider) -> None:
        self._settings = settings
        self._ai = ai_provider
        self._store = PersonaStore(settings)
        self._planner = SessionPlanner(ai_provider, settings)
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False

    # ── Single session ─────────────────────────────────────────────────────────

    async def run_session(self) -> SessionRecord:
        """
        Full pipeline: rotate personas → pick persona →
        generate plan → open browser → execute plan → record result.
        """
        # 1. Retire old personas
        self._store.rotate_old()

        # 2. Pick least-recently-used persona
        persona = self._store.pick_for_session()
        if not persona:
            raise RuntimeError(
                "No active personas found. Run 'i-fake gen-persona' to create one first."
            )

        log.info("Session persona: %s (%s)", persona.name, persona.id[:8])

        # 4. Generate browsing plan
        plan = await self._planner.create_plan(persona)

        # 5. Execute in browser
        record = SessionRecord(plan_id=plan.id, persona_id=persona.id)
        record.status = SessionStatus.RUNNING
        record.started_at = datetime.utcnow()

        browser = BrowserController(self._settings, persona.id)
        try:
            await browser.start()
            completed = await browser.execute_plan(plan)
            record.actions_completed = completed
            record.status = SessionStatus.COMPLETED
        except Exception as exc:
            log.error("Session failed: %s", exc, exc_info=True)
            record.status = SessionStatus.FAILED
            record.error = str(exc)
        finally:
            await browser.stop()
            record.completed_at = datetime.utcnow()
            self._store.mark_used(persona.id)
            self._save_record(record)

        log.info(
            "Session %s %s — %d/%d actions  (%.1f min)",
            record.id[:8],
            record.status.value.upper(),
            record.actions_completed,
            len(plan.actions),
            (
                (record.completed_at - record.started_at).total_seconds() / 60
                if record.completed_at and record.started_at
                else 0
            ),
        )
        return record

    async def run_endless(self) -> None:
        """
        Open one browser for one persona and keep browsing forever.
        Generates a fresh plan after each plan completes, with a short
        human-like pause between plans.  Runs until cancelled / Ctrl-C.
        """
        # Ensure persona pool is ready
        self._store.rotate_old()
        persona = self._store.pick_for_session()
        if not persona:
            raise RuntimeError(
                "No active personas found. Run 'i-fake gen-persona' to create one first."
            )

        log.info(
            "Endless session — persona: %s (%s)  (Ctrl-C to stop)",
            persona.name, persona.id[:8],
        )

        browser = BrowserController(self._settings, persona.id)
        await browser.start()
        plan_count = 0
        try:
            while True:
                plan_count += 1
                log.info("Planning mini-session #%d …", plan_count)
                plan = await self._planner.create_plan(persona)

                record = SessionRecord(plan_id=plan.id, persona_id=persona.id)
                record.status = SessionStatus.RUNNING
                record.started_at = datetime.utcnow()
                try:
                    completed = await browser.execute_plan(plan)
                    record.actions_completed = completed
                    record.status = SessionStatus.COMPLETED
                except Exception as exc:
                    log.error("Mini-session #%d failed: %s", plan_count, exc, exc_info=True)
                    record.status = SessionStatus.FAILED
                    record.error = str(exc)
                finally:
                    record.completed_at = datetime.utcnow()
                    self._store.mark_used(persona.id)
                    self._save_record(record)

                log.info(
                    "Mini-session #%d done (%d actions) — starting next …",
                    plan_count, record.actions_completed,
                )
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await browser.stop()
            log.info("Endless session ended after %d mini-sessions.", plan_count)


    def start_scheduler(self) -> None:
        """
        Schedule ``run_session`` to fire ``sessions_per_day`` times per day
        with ±30 % random jitter so the cadence looks organic.
        """
        interval_secs = int(86_400 / max(1, self._settings.sessions_per_day))
        jitter = int(interval_secs * 0.30)

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._scheduled_run,
            trigger=IntervalTrigger(seconds=interval_secs),
            id="session_runner",
            replace_existing=True,
            jitter=jitter,
        )
        self._scheduler.start()
        self._running = True
        log.info(
            "Scheduler started — %d sessions/day, every ~%d min (±%d s jitter)",
            self._settings.sessions_per_day,
            interval_secs // 60,
            jitter,
        )

    def stop_scheduler(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._running = False
        log.info("Scheduler stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _scheduled_run(self) -> None:
        """Wrapper so scheduler exceptions are logged rather than swallowed."""
        try:
            await self.run_session()
        except Exception as exc:
            log.error("Scheduled session raised: %s", exc, exc_info=True)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _save_record(self, record: SessionRecord) -> None:
        path = self._settings.data_dir / "sessions" / f"session_{record.id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
