"""Human behaviour simulation primitives: mouse curves, typing delays, scrolling."""

from __future__ import annotations

import asyncio
import random
from typing import NamedTuple


class Point(NamedTuple):
    x: float
    y: float


# ── Bézier mouse path ──────────────────────────────────────────────────────────


def _cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    """Evaluate a cubic Bézier curve at parameter *t* ∈ [0, 1]."""
    mt = 1 - t
    x = mt**3 * p0.x + 3 * mt**2 * t * p1.x + 3 * mt * t**2 * p2.x + t**3 * p3.x
    y = mt**3 * p0.y + 3 * mt**2 * t * p1.y + 3 * mt * t**2 * p2.y + t**3 * p3.y
    return Point(x, y)


def generate_mouse_path(
    start: Point,
    end: Point,
    num_points: int = 12,
    wobble: float = 55.0,
) -> list[Point]:
    """
    Return a list of intermediate Points along a random cubic Bézier curve from
    *start* to *end*, simulating natural hand-movement.
    """
    dx, dy = end.x - start.x, end.y - start.y

    cp1 = Point(
        start.x + dx * random.uniform(0.15, 0.35) + random.uniform(-wobble, wobble),
        start.y + dy * random.uniform(0.05, 0.30) + random.uniform(-wobble, wobble),
    )
    cp2 = Point(
        start.x + dx * random.uniform(0.65, 0.85) + random.uniform(-wobble, wobble),
        start.y + dy * random.uniform(0.70, 0.95) + random.uniform(-wobble, wobble),
    )

    return [
        _cubic_bezier(start, cp1, cp2, end, i / (num_points - 1))
        for i in range(num_points)
    ]


# ── Typing ─────────────────────────────────────────────────────────────────────


def typing_delay_ms() -> float:
    """
    Per-keystroke delay in milliseconds.
    Gaussian around 75 ms (≈ 80 WPM), clamped to a realistic minimum.
    """
    return max(28.0, random.gauss(75.0, 22.0))


def occasional_pause_chance(probability: float = 0.04) -> float:
    """
    With *probability*, return a 'thinking pause' duration in seconds.
    Otherwise return 0.  Simulates mid-sentence hesitation.
    """
    return random.uniform(0.4, 2.8) if random.random() < probability else 0.0


# ── Scrolling ──────────────────────────────────────────────────────────────────


def scroll_delta(min_px: int = 80, max_px: int = 420) -> int:
    """Natural scroll wheel delta in pixels."""
    return random.randint(min_px, max_px)


# ── Pauses ─────────────────────────────────────────────────────────────────────


def reading_pause(words_on_screen: int = 90, wpm: float = 240.0) -> float:
    """
    Estimate seconds a human would spend skimming *words_on_screen* words at
    *wpm* words-per-minute, with Gaussian noise.
    """
    base = (words_on_screen / wpm) * 60
    return max(1.5, random.gauss(base, base * 0.2))


async def human_sleep(min_s: float, max_s: float) -> None:
    """
    Async sleep for a Gaussian-shaped random duration within [min_s, max_s].
    """
    mid = (min_s + max_s) / 2.0
    spread = (max_s - min_s) / 4.0
    duration = max(min_s, min(max_s, random.gauss(mid, spread)))
    await asyncio.sleep(duration)
