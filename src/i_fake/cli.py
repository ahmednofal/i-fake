"""
CLI entry point.

Commands
--------
i-fake start          — run the scheduler continuously (Ctrl-C to stop)
i-fake run-once       — run exactly one session right now
i-fake start -s N     — run exactly N sessions then exit
i-fake gen-persona    — generate and save one new persona
i-fake personas       — list all stored personas
i-fake sessions       — list recent session records
i-fake config         — show current settings
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich import box, print as rprint
from rich.table import Table

from .ai.anthropic_provider import AnthropicProvider
from .ai.gemini_provider import GeminiProvider
from .ai.local_provider import LocalProvider
from .ai.openai_provider import OpenAIProvider
from .ai.provider import AIProvider
from .ai.prompts import PERSONA_SYSTEM, persona_user_prompt
from .browser import _find_firefox_executable, _find_firefox_real_profile, seed_persona_profile
from .config import Settings, get_settings
from .orchestrator import Orchestrator
from .persona import PersonaStore
from .models import SessionRecord
from .utils.logger import get_logger, setup_logger

app = typer.Typer(
    name="i-fake",
    help="AI-powered fake traffic generator — poison your ad-tracking profile.",
    add_completion=False,
)


# ── Provider factory ───────────────────────────────────────────────────────────

def _build_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            rprint("[bold red]Error:[/bold red] IFAKE_GEMINI_API_KEY is not set.")
            rprint("Get a free key at [link]https://aistudio.google.com/app/apikey[/link]")
            raise typer.Exit(1)
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    elif settings.ai_provider == "openai":
        if not settings.openai_api_key:
            rprint("[bold red]Error:[/bold red] IFAKE_OPENAI_API_KEY is not set.")
            raise typer.Exit(1)
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    elif settings.ai_provider == "anthropic":
        if not settings.anthropic_api_key:
            rprint("[bold red]Error:[/bold red] IFAKE_ANTHROPIC_API_KEY is not set.")
            raise typer.Exit(1)
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    else:
        return LocalProvider(settings.local_model_url, settings.local_model_name)


# ── Commands ───────────────────────────────────────────────────────────────────

@app.command()
def start(
    sessions: Optional[int] = typer.Option(
        None, "--sessions", "-s",
        help="Run exactly N sessions then exit. Omit to run indefinitely.",
    ),
    headed: bool = typer.Option(False, "--headed", help="Show the browser window (disables headless mode)."),
) -> None:
    """Start the fake-traffic engine."""
    settings = get_settings()
    settings.headless = not headed
    settings.ensure_dirs()
    setup_logger(level=settings.log_level, log_dir=settings.data_dir / "logs")

    provider = _build_provider(settings)
    orch = Orchestrator(settings, provider)

    async def _run() -> None:
        if sessions:
            for i in range(sessions):
                rprint(f"\n[bold cyan]━━ Session {i + 1}/{sessions} ━━[/bold cyan]")
                await orch.run_session()
        else:
            rprint("[bold green]Scheduler started[/bold green] — press Ctrl-C to stop.")
            orch.start_scheduler()
            try:
                while True:
                    await asyncio.sleep(60)
            except (KeyboardInterrupt, asyncio.CancelledError):
                orch.stop_scheduler()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted — bye.[/yellow]")


@app.command("run-once")
def run_once(
    headed: bool = typer.Option(False, "--headed", help="Show the browser window (disables headless mode)."),
    endless: bool = typer.Option(False, "--endless", help="Keep browsing forever: generate a new plan after each one finishes."),
) -> None:
    """Run a single browsing session immediately and exit (or loop forever with --endless)."""
    settings = get_settings()
    settings.headless = not headed
    settings.ensure_dirs()
    setup_logger(level=settings.log_level, log_dir=settings.data_dir / "logs")

    provider = _build_provider(settings)
    orch = Orchestrator(settings, provider)

    if endless:
        try:
            asyncio.run(orch.run_endless())
        except KeyboardInterrupt:
            rprint("\n[yellow]Interrupted.[/yellow]")
        return

    try:
        record = asyncio.run(orch.run_session())
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted.[/yellow]")
        raise typer.Exit(1)

    colour = "green" if record.status.value == "completed" else "red"
    rprint(
        f"[{colour}]{record.status.value.upper()}[/{colour}]"
        f"  •  {record.actions_completed} actions"
        f"  •  session id: {record.id[:8]}"
    )


@app.command()
def personas() -> None:
    """List all stored personas."""
    settings = get_settings()
    settings.ensure_dirs()
    store = PersonaStore(settings)
    all_p = store.load_all()

    if not all_p:
        rprint("[yellow]No personas found. Run 'i-fake gen-persona' to create one.[/yellow]")
        return

    table = Table(title=f"Personas ({len(all_p)} total)", box=box.ROUNDED)
    table.add_column("ID", style="dim", width=9)
    table.add_column("Name")
    table.add_column("Age")
    table.add_column("Occupation")
    table.add_column("Location")
    table.add_column("Active", justify="center")
    table.add_column("Last used")

    for p in all_p:
        table.add_row(
            p.id[:8],
            p.name,
            p.age_range.value,
            p.occupation,
            p.location,
            "✅" if p.active else "❌",
            p.last_used.strftime("%Y-%m-%d %H:%M") if p.last_used else "—",
        )
    rprint(table)


@app.command("gen-persona")
def gen_persona(
    constraints: Optional[str] = typer.Option(
        None, "--constraints", "-c",
        help=(
            'Pin demographic attributes, e.g.: '
            '"Arab Egyptian Muslim male, 30 years old, Cairo"'
        ),
    ),
) -> None:
    """Generate and save one new fake persona."""
    settings = get_settings()
    settings.ensure_dirs()
    setup_logger(level=settings.log_level)

    provider = _build_provider(settings)
    store = PersonaStore(settings)

    async def _run() -> None:
        user_prompt = persona_user_prompt(constraints or "")
        rprint("[dim]─── SYSTEM PROMPT ───[/dim]")
        rprint(f"[dim]{PERSONA_SYSTEM}[/dim]")
        rprint("[dim]─── USER PROMPT ─────[/dim]")
        rprint(f"[dim]{user_prompt}[/dim]")
        rprint("[dim]──────────────────────[/dim]\n")
        rprint("Generating persona …")
        p = await provider.generate_persona(constraints=constraints or "")
        store.save(p)
        rprint(f"\n[bold green]✔  {p.name}[/bold green] [{p.id[:8]}]")
        rprint(f"   Age: {p.age_range.value}  |  {p.gender.value}  |  {p.occupation}")
        rprint(f"   Location: {p.location}")
        rprint(f"   Interests: {', '.join(p.interests)}")
        rprint(f"   Sites:     {', '.join(p.favorite_sites)}")
        rprint(f"   Shopping:  {', '.join(p.shopping_categories)}")

    asyncio.run(_run())


@app.command()
def sessions() -> None:
    """List recent session records."""
    settings = get_settings()
    sessions_dir = settings.data_dir / "sessions"
    records: list[SessionRecord] = []
    for path in sorted(sessions_dir.glob("session_*.json"), reverse=True)[:20]:
        try:
            records.append(SessionRecord.model_validate_json(path.read_text()))
        except Exception:
            continue

    if not records:
        rprint("[yellow]No session records found.[/yellow]")
        return

    table = Table(title="Recent sessions (latest 20)", box=box.ROUNDED)
    table.add_column("ID", style="dim", width=9)
    table.add_column("Persona", width=9, style="dim")
    table.add_column("Status")
    table.add_column("Actions", justify="right")
    table.add_column("Started")
    table.add_column("Duration")

    for r in records:
        dur = "—"
        if r.started_at and r.completed_at:
            secs = int((r.completed_at - r.started_at).total_seconds())
            dur = f"{secs // 60}m {secs % 60}s"
        colour = {"completed": "green", "failed": "red", "running": "yellow"}.get(
            r.status.value, "white"
        )
        table.add_row(
            r.id[:8],
            r.persona_id[:8],
            f"[{colour}]{r.status.value}[/{colour}]",
            str(r.actions_completed),
            r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "—",
            dur,
        )
    rprint(table)


@app.command()
def config() -> None:
    """Show current configuration (API keys are masked)."""
    settings = get_settings()
    table = Table(title="Configuration", box=box.ROUNDED)
    table.add_column("Setting")
    table.add_column("Value")

    for field, value in settings.model_dump().items():
        if "api_key" in field and isinstance(value, str) and len(value) > 10:
            value = value[:6] + "…" + value[-4:]
        table.add_row(field, str(value))
    rprint(table)


@app.command("delete-persona")
def delete_persona(
    persona_ids: Optional[list[str]] = typer.Argument(None, help="One or more persona ID prefixes to delete."),
    all_personas_flag: bool = typer.Option(False, "--all", help="Delete every persona."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete one or more personas and their browser profiles."""
    settings = get_settings()
    settings.ensure_dirs()
    store = PersonaStore(settings)
    all_stored = store.load_all()

    if all_personas_flag:
        to_delete = all_stored
        if not to_delete:
            rprint("[yellow]No personas to delete.[/yellow]")
            raise typer.Exit(0)
    else:
        if not persona_ids:
            rprint("[red]Provide at least one ID prefix, or use --all.[/red]")
            raise typer.Exit(1)
        to_delete = []
        for pid in persona_ids:
            matches = [p for p in all_stored if p.id.startswith(pid)]
            if not matches:
                rprint(f"[red]No persona matching '{pid}'.[/red]")
                continue
            if len(matches) > 1:
                rprint(f"[red]Ambiguous — {len(matches)} personas match '{pid}'. Use more characters.[/red]")
                for p in matches:
                    rprint(f"  {p.id[:8]}  {p.name}")
                continue
            to_delete.append(matches[0])

    if not to_delete:
        raise typer.Exit(1)

    if not yes:
        rprint("Will delete:")
        for p in to_delete:
            rprint(f"  [yellow]{p.id[:8]}[/yellow]  {p.name}")
        typer.confirm(f"Delete {len(to_delete)} persona(s)?", abort=True)

    import shutil as _shutil
    for p in to_delete:
        store.delete(p.id)
        profile_dir = settings.data_dir / "profiles" / p.id
        if profile_dir.exists():
            _shutil.rmtree(profile_dir, ignore_errors=True)
        rprint(f"[green]✔  Deleted {p.name} ({p.id[:8]})[/green]")


@app.command("seed-profile")
def seed_profile_cmd(
    persona_id: Optional[str] = typer.Argument(None, help="Persona ID prefix to seed (default: all personas)."),
    real_profile: Optional[str] = typer.Option(None, "--from", help="Path to real Firefox profile (auto-detected if omitted)."),
) -> None:
    """Copy cookies/localStorage from your real Firefox profile into persona profiles."""
    settings = get_settings()
    src = real_profile or settings.firefox_real_profile or _find_firefox_real_profile()
    if not src:
        rprint("[red]Could not find a real Firefox profile.[/red]")
        rprint("Start Firefox once to create a profile, then re-run this command.")
        rprint("Or pass --from /path/to/your/firefox/profile manually.")
        raise typer.Exit(1)

    rprint(f"Seeding from: [cyan]{src}[/cyan]")

    store = PersonaStore(settings)
    personas = store.active_personas()
    if not personas:
        rprint("[yellow]No personas found — run [bold]i-fake gen-persona[/bold] first.[/yellow]")
        raise typer.Exit(1)

    targets = [p for p in personas if not persona_id or p.id.startswith(persona_id)]
    if not targets:
        rprint(f"[red]No persona matching '{persona_id}'.[/red]")
        raise typer.Exit(1)

    for persona in targets:
        profile_dir = settings.data_dir / "profiles" / persona.id
        profile_dir.mkdir(parents=True, exist_ok=True)
        # Force re-seed by removing existing cookies.sqlite
        (profile_dir / "cookies.sqlite").unlink(missing_ok=True)
        seed_persona_profile(profile_dir, src)
        rprint(f"  ✔  [green]{persona.name}[/green] ({persona.id[:8]})")

    rprint(f"[bold green]Done — {len(targets)} profile(s) seeded.[/bold green]")


if __name__ == "__main__":
    app()
