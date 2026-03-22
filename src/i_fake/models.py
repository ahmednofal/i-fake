"""Core Pydantic data models used throughout i_fake."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Persona ────────────────────────────────────────────────────────────────────


class AgeRange(str, Enum):
    TEEN = "13-17"
    YOUNG_ADULT = "18-25"
    ADULT = "26-35"
    MIDDLE_AGED = "36-50"
    SENIOR = "51-70"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"


class IncomeBracket(str, Enum):
    LOW = "low"
    MIDDLE = "middle"
    HIGH = "high"


class Persona(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    age_range: AgeRange
    gender: Gender
    occupation: str
    location: str  # "City, Country"
    interests: list[str]
    shopping_categories: list[str]
    favorite_sites: list[str]  # bare domains, e.g. "reddit.com"
    search_style: str  # short description of how the persona types queries
    income_bracket: IncomeBracket
    political_leaning: Optional[str] = None
    personality_notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    active: bool = True


# ── Browsing plan ──────────────────────────────────────────────────────────────


class ActionType(str, Enum):
    SEARCH = "search"
    NAVIGATE = "navigate"
    CLICK_LINK = "click_link"
    SCROLL = "scroll"
    READ = "read"
    FILL_FORM = "fill_form"
    HOVER = "hover"
    GO_BACK = "go_back"
    WATCH_VIDEO = "watch_video"
    ADD_TO_CART = "add_to_cart"
    IDLE = "idle"


class BrowsingAction(BaseModel):
    type: ActionType
    target: Optional[str] = None   # URL, search query, CSS selector …
    value: Optional[str] = None    # text to type, form value …
    dwell_min: float = 2.0         # seconds
    dwell_max: float = 8.0
    description: str               # human-readable label for logging

    @field_validator("dwell_min")
    @classmethod
    def _cap_min(cls, v: float) -> float:
        return min(v, 4.0)

    @field_validator("dwell_max")
    @classmethod
    def _cap_max(cls, v: float) -> float:
        return min(v, 8.0)


class BrowsingPlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona_id: str
    session_theme: str
    actions: list[BrowsingAction]
    estimated_duration_minutes: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Session record ─────────────────────────────────────────────────────────────


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str
    persona_id: str
    status: SessionStatus = SessionStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    actions_completed: int = 0
    error: Optional[str] = None
