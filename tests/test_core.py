"""Unit tests for core models and human-simulation utilities."""

from __future__ import annotations

import math

import pytest

from i_fake.models import (
    ActionType,
    AgeRange,
    BrowsingAction,
    BrowsingPlan,
    Gender,
    IncomeBracket,
    Persona,
    SessionRecord,
    SessionStatus,
)
from i_fake.utils.human_sim import (
    Point,
    generate_mouse_path,
    occasional_pause_chance,
    scroll_delta,
    typing_delay_ms,
)


# ── Persona model ──────────────────────────────────────────────────────────────


def test_persona_defaults():
    p = Persona(
        name="Ada Lovelace",
        age_range=AgeRange.ADULT,
        gender=Gender.FEMALE,
        occupation="Mathematician",
        location="London, UK",
        interests=["mathematics", "poetry", "computing"],
        shopping_categories=["books", "art supplies"],
        favorite_sites=["wikipedia.org", "arxiv.org"],
        search_style="precise academic queries",
        income_bracket=IncomeBracket.MIDDLE,
    )
    assert p.name == "Ada Lovelace"
    assert p.active is True
    assert p.last_used is None
    assert len(p.id) == 36  # UUID4


def test_persona_serialisation_roundtrip():
    p = Persona(
        name="Test User",
        age_range=AgeRange.YOUNG_ADULT,
        gender=Gender.NON_BINARY,
        occupation="Designer",
        location="Berlin, Germany",
        interests=["design", "music"],
        shopping_categories=["fashion"],
        favorite_sites=["dribbble.com"],
        search_style="visual keyword searches",
        income_bracket=IncomeBracket.MIDDLE,
    )
    json_str = p.model_dump_json()
    p2 = Persona.model_validate_json(json_str)
    assert p2.id == p.id
    assert p2.name == p.name


# ── BrowsingPlan model ─────────────────────────────────────────────────────────


def test_browsing_plan_creation():
    action = BrowsingAction(
        type=ActionType.SEARCH,
        value="best hiking boots 2026",
        dwell_min=2.0,
        dwell_max=5.0,
        description="Search for hiking boots",
    )
    plan = BrowsingPlan(
        persona_id="test-persona-id",
        session_theme="shopping for hiking gear",
        actions=[action],
        estimated_duration_minutes=10.0,
    )
    assert len(plan.actions) == 1
    assert plan.actions[0].type == ActionType.SEARCH


# ── SessionRecord ──────────────────────────────────────────────────────────────


def test_session_record_defaults():
    r = SessionRecord(plan_id="p1", persona_id="per1")
    assert r.status == SessionStatus.PENDING
    assert r.actions_completed == 0


# ── Human simulation utilities ─────────────────────────────────────────────────


def test_mouse_path_length():
    start = Point(100, 100)
    end = Point(800, 600)
    path = generate_mouse_path(start, end, num_points=20)
    assert len(path) == 20
    # First and last points should be close to start/end
    assert math.isclose(path[0].x, start.x, abs_tol=1)
    assert math.isclose(path[-1].x, end.x, abs_tol=1)


def test_typing_delay_range():
    delays = [typing_delay_ms() for _ in range(200)]
    assert all(d >= 28 for d in delays)
    # Most delays should be between 30 and 180 ms
    in_range = sum(1 for d in delays if 30 <= d <= 180)
    assert in_range / len(delays) > 0.95


def test_scroll_delta_range():
    deltas = [scroll_delta() for _ in range(100)]
    assert all(80 <= d <= 420 for d in deltas)


def test_occasional_pause_always_zero_or_positive():
    pauses = [occasional_pause_chance() for _ in range(500)]
    assert all(p == 0.0 or p >= 0.4 for p in pauses)
