"""
Shared LLM prompt templates used by all AI provider implementations.
Keeping them here avoids duplication and coupling between provider modules.
"""

# ── Persona generation ─────────────────────────────────────────────────────────

PERSONA_SYSTEM = (
    "You are generating fake online user personas for a privacy tool that obfuscates "
    "ad-tracking and behavioural profiling. Return ONLY valid JSON matching the schema "
    "exactly — no markdown fences, no commentary, no extra keys.\n"
    "DIVERSITY RULE: Do NOT default occupation to software engineer, developer, or any "
    "tech role unless explicitly specified. Draw from the full range of human occupations: "
    "teachers, farmers, drivers, shop owners, students, doctors, craftspeople, etc. "
    "Vary age, gender, nationality, religion, income, and cultural background broadly."
)

PERSONA_SCHEMA = """\
{
  "name": "fictional full name (string)",
  "age_range": "one of: 13-17 | 18-25 | 26-35 | 36-50 | 51-70",
  "gender": "one of: male | female | non_binary",
  "occupation": "job title (string)",
  "location": "City, Country (string)",
  "interests": ["list of 5–10 specific interests"],
  "shopping_categories": ["list of 3–6 shopping categories"],
  "favorite_sites": ["list of 4–8 domain names, e.g. reddit.com"],
  "search_style": "one sentence: how they type search queries",
  "income_bracket": "one of: low | middle | high",
  "political_leaning": "optional string or null",
  "personality_notes": "2–3 sentences about browsing habits and online behaviour"
}"""

PERSONA_USER = (
    "Generate one unique, realistic, and internally consistent persona. "
    f"Schema:\n{PERSONA_SCHEMA}"
)


def persona_user_prompt(constraints: str = "", existing_names: list[str] | None = None) -> str:
    """
    Build the persona generation user prompt, optionally pinning demographics
    and/or avoiding duplication with already-existing personas.
    """
    avoid = ""
    if existing_names:
        avoid = (
            f" The following personas already exist — make this one clearly DIFFERENT "
            f"in demographics, culture, and interests: {', '.join(existing_names)}."
        )
    if constraints:
        return (
            f"Generate one unique, realistic, and internally consistent persona "
            f"that matches these demographic constraints EXACTLY: {constraints}.{avoid} "
            f"Fill ALL other fields (interests, shopping, sites, search style, "
            f"personality notes) to be realistic and coherent with the constraints.\n"
            f"Schema:\n{PERSONA_SCHEMA}"
        )
    return (
        f"Generate one unique, realistic, and internally consistent persona.{avoid}\n"
        f"Schema:\n{PERSONA_SCHEMA}"
    )

# ── Session planning ───────────────────────────────────────────────────────────

PLAN_SYSTEM = (
    "You are generating realistic web browsing session plans for a fake user persona. "
    "The goal is authentic-looking traffic that will be indistinguishable from a real "
    "human browsing the web. Return ONLY valid JSON — no markdown fences, no commentary.\n"
    "For 'search' actions, set 'target' to null and 'value' to the search query string. "
    "The search engine will be chosen automatically to match the persona.\n\n"
    "VARIETY RULES — follow all of these:\n"
    "1. Each session must have a DISTINCT theme — pick from: news, shopping, entertainment, "
    "social media, video watching, sports, food, travel, finance, religion, gaming, education, "
    "local services, health, DIY, cooking, music, tech, fashion, parenting, etc.\n"
    "2. Do NOT repeat themes that were recently used (provided in the prompt).\n"
    "3. Mix action types — NOT just search+navigate+scroll. Include watch_video, click_link, "
    "add_to_cart, go_back, idle, hover as appropriate.\n"
    "4. Vary the sites visited — don't use the same domains every session.\n"
    "5. Search queries must sound like a real person typed them — typos, fragments, local slang.\n\n"
    "BEHAVIOR RULES — make sessions feel curious and immersive:\n"
    "6. After a search the person READS the result snippets — include 'scroll' or 'read' before clicking.\n"
    "7. After navigating to a page the person READS it — use 'read' with dwell 10-25s, not just 'scroll'.\n"
    "8. Real people follow rabbit holes: search → click result → read → click a related link → read more.\n"
    "9. Include 'go_back' when the person would naturally return to results and try a different link.\n"
    "10. Sessions must feel like genuine curiosity-driven exploration, NOT a mechanical checklist."
)

PLAN_SCHEMA = """\
{
  "session_theme": "short phrase describing the session goal",
  "estimated_duration_minutes": <number>,
  "actions": [
    {
      "type": "<one of: search | navigate | click_link | scroll | read | fill_form | hover | go_back | watch_video | add_to_cart | idle>",
      "target": "<URL, search query, or CSS selector — or null>",
      "value":  "<text to type or other value — or null>",
      "dwell_min": <seconds — 1-3 for scroll/hover/click, 10-20 for read/watch_video>,
      "dwell_max": <seconds — 2-6 for scroll/hover/click, 20-40 for read/watch_video>,
      "description": "<short human-readable description>"
    }
  ]
}"""


def plan_user_prompt(
    persona_summary: str,
    recent_themes: list[str] | None = None,
    activity_log: list[str] | None = None,
) -> str:
    avoid = ""
    if recent_themes:
        avoid = f"\nRECENT THEMES TO AVOID: {', '.join(recent_themes)}\n"
    history = ""
    if activity_log:
        # Show the last 10 entries most-recent-last so the AI sees the trajectory
        entries = activity_log[-10:]
        history = (
            "\nBROWSING HISTORY (most recent last — let curiosity naturally evolve from this):\n"
            + "\n".join(f"  • {e}" for e in entries)
            + "\n"
        )
    return (
        f"Persona:\n{persona_summary}\n{avoid}{history}\n"
        f"Create a 5\u20138 step browsing session that feels like a genuinely curious human exploring the web.\n"
        f"The person should CONSUME content (read articles, watch videos) \u2014 not just hop between pages.\n"
        f"Always include 'read' actions (dwell 10-25s) after navigating to content pages.\n"
        f"Let the browsing history above subtly shape where their curiosity drifts \u2014 interests deepen, "
        f"new threads branch off, old ones resurface. Don't repeat the same session \u2014 evolve.\n"
        f"Keep descriptions concise (under 60 characters each).\n"
        f"Schema:\n{PLAN_SCHEMA}"
    )


# ── Search queries ─────────────────────────────────────────────────────────────

QUERY_SYSTEM = "Return ONLY a JSON array of strings. No commentary, no markdown."


def query_user_prompt(persona_summary: str, topic: str, n: int) -> str:
    return (
        f"Generate {n} realistic Google search queries about '{topic}' "
        f"for this persona:\n{persona_summary}\n"
        "Queries should match their search style and sound natural."
    )
