"""
Browser controller — Playwright + playwright-stealth with full human simulation.

Key anti-detection layers:
  • playwright-stealth patches (navigator.webdriver, plugins, languages, etc.)
  • Persistent browser profile per persona (cookies/localStorage survive between sessions)
  • Pinned fingerprint per persona (same UA, viewport, timezone across all sessions)
  • Bézier-curve mouse movement between every click target
  • Gaussian-distributed typing delays with occasional hesitation pauses
  • Natural scrolling patterns with varied deltas
  • Slow-start navigation (domcontentloaded, not networkidle)
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, BrowserType, Page, async_playwright
from playwright_stealth import Stealth

from .config import Settings
from .models import ActionType, BrowsingAction, BrowsingPlan
from .utils.human_sim import (
    Point,
    generate_mouse_path,
    human_sleep,
    occasional_pause_chance,
    scroll_delta,
    typing_delay_ms,
)
from .utils.logger import get_logger

log = get_logger("i_fake.browser")

# ── Deep stealth init script — runs before any page JS ────────────────────────
# Patches the most commonly fingerprinted automation signals.
_STEALTH_INIT_SCRIPT = """
(() => {
  // 1. Remove navigator.webdriver
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // 2. Restore window.chrome (absent in automated Chromium)
  if (!window.chrome) {
    window.chrome = {
      app: { isInstalled: false, InstallState: {}, RunningState: {} },
      csi: () => {},
      loadTimes: () => {},
      runtime: {},
    };
  }

  // 3. Realistic plugin list (empty in headless)
  const makePlugin = (name, filename, desc, mimeTypes) => {
    const plugin = { name, filename, description: desc, length: mimeTypes.length };
    mimeTypes.forEach((mt, i) => { plugin[i] = mt; });
    return plugin;
  };
  const plugins = [
    makePlugin('Chrome PDF Plugin', 'internal-pdf-viewer', 'Portable Document Format', []),
    makePlugin('Chrome PDF Viewer',  'mhjfbmdgcfjbbpaeojofohoefgiehjai', '', []),
    makePlugin('Native Client',      'internal-nacl-plugin', '', []),
  ];
  Object.defineProperty(navigator, 'plugins', {
    get: () => { const arr = plugins; arr.refresh = () => {}; return arr; },
  });

  // 4. languages
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

  // 5. Permissions API — make 'notifications' return 'default' not 'denied'
  const origQuery = window.Permissions && window.Permissions.prototype.query;
  if (origQuery) {
    window.Permissions.prototype.query = function(params) {
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: 'default', onchange: null });
      }
      return origQuery.apply(this, arguments);
    };
  }

  // 6. Hide CDP-injected properties
  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
})();
"""

# ── Fingerprint pools ──────────────────────────────────────────────────────────

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 2560, "height": 1440},
    {"width": 1600, "height": 900},
]

_USER_AGENTS = [
    # Windows — Chrome 134
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # macOS — Chrome 134
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Windows — Chrome 133
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    # macOS — Chrome 133
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    # Windows — Firefox 135
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    # macOS — Firefox 135
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    # macOS — Safari 17.6
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "America/Denver",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Asia/Tokyo",
    "Australia/Sydney",
]


def _seeded_choice(options: list, seed: str) -> object:
    """Pick a stable item from *options* deterministically from *seed*."""
    idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(options)
    return options[idx]


def _find_firefox_executable() -> str:
    """Return the path to the installed Firefox binary, or empty string if not found."""
    # Explicit common locations on Linux / macOS
    candidates = [
        "/usr/bin/firefox",
        "/snap/bin/firefox",
        "/usr/lib/firefox/firefox",
        "/usr/lib64/firefox/firefox",
        "/opt/firefox/firefox",
        "/Applications/Firefox.app/Contents/MacOS/firefox",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    # Fall back to PATH
    found = shutil.which("firefox")
    return found or ""


def _find_firefox_real_profile() -> str:
    """
    Return the path to the user's default Firefox profile, or empty string.
    Checks both ~/.mozilla/firefox and ~/snap/firefox (snap package) on Linux.
    """
    candidates = [
        Path.home() / "snap" / "firefox" / "common" / ".mozilla" / "firefox" / "profiles.ini",
        Path.home() / ".mozilla" / "firefox" / "profiles.ini",
    ]
    for profiles_ini in candidates:
        if not profiles_ini.exists():
            continue
        base_dir = profiles_ini.parent
        text = profiles_ini.read_text(errors="replace")
        current_path: str = ""
        is_default = False
        is_relative = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                if is_default and current_path:
                    break
                is_default = False
                is_relative = False
                current_path = ""
            elif line.lower() == "default=1":
                is_default = True
            elif line.startswith("Path="):
                current_path = line.split("=", 1)[1].strip()
            elif line.startswith("IsRelative=1"):
                is_relative = True
        if is_default and current_path:
            resolved = str(base_dir / current_path) if is_relative else current_path
            if Path(resolved).is_dir():
                return resolved
    return ""


# Files worth copying from a real Firefox profile for cookie/session state.
# Intentionally excludes places.sqlite (history — large and not needed).
_PROFILE_SEED_FILES = [
    "cookies.sqlite",
    "cookies.sqlite-wal",
    "cookies.sqlite-shm",
    "webappsstore.sqlite",       # localStorage
    "key4.db",                   # credential store (needed to decrypt saved passwords)
    "logins.json",               # saved logins
    "cert9.db",                  # certificate store
    "sessionstore.jsonlz4",      # last session tabs (optional but realistic)
]

_FIREFOX_LOCK_FILES = ("lock", ".parentlock", "parent.lock")


def _kill_firefox() -> None:
    """Terminate any running Firefox processes so the profile lock is released."""
    try:
        # pkill -x only matches exact process name — snap Firefox runs as a full path,
        # so use pkill -f to match anything containing 'firefox/firefox' in the cmdline.
        result = subprocess.run(
            ["pkill", "-f", r"firefox/firefox"],
            capture_output=True,
        )
        if result.returncode == 0:
            import time; time.sleep(2.0)  # wait for all child processes to exit
            log.debug("Killed running Firefox process(es).")
    except Exception:
        pass


def _clear_profile_locks(profile_dir: Path) -> None:
    """Remove Firefox profile lock files so Playwright can open the profile."""
    for lock in _FIREFOX_LOCK_FILES:
        (profile_dir / lock).unlink(missing_ok=True)


def seed_persona_profile(persona_profile_dir: Path, real_profile: str) -> None:
    """
    Copy key files from *real_profile* into *persona_profile_dir* if the
    persona profile is empty (first run).  Removes Firefox lock files so
    Playwright can open the profile.
    """
    if not real_profile or not Path(real_profile).is_dir():
        return
    # Only seed once — if cookies.sqlite already exists, skip
    if (persona_profile_dir / "cookies.sqlite").exists():
        return

    src = Path(real_profile)
    log.info("Seeding persona profile from real Firefox profile: %s", src)
    for fname in _PROFILE_SEED_FILES:
        src_file = src / fname
        if src_file.exists():
            try:
                shutil.copy2(src_file, persona_profile_dir / fname)
                log.debug("  copied %s", fname)
            except Exception as exc:
                log.debug("  could not copy %s: %s", fname, exc)


class BrowserController:
    """
    Manages a single browser session with human-like behaviour.

    Pass *persona_id* so the controller uses (and persists) that persona's
    browser profile — cookies, localStorage, and fingerprint are all stable
    across sessions for the same persona.
    """

    def __init__(self, settings: Settings, persona_id: str) -> None:
        self._settings = settings
        self._persona_id = persona_id
        self._profile_dir: Path = settings.data_dir / "profiles" / persona_id
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._attached: bool = False   # True when we connected to a running browser
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        # Stable fingerprint seeded from persona_id
        self._viewport: dict = _seeded_choice(_VIEWPORTS, persona_id + "_vp")  # type: ignore[assignment]
        self._ua: str = _seeded_choice(_USER_AGENTS, persona_id + "_ua")  # type: ignore[assignment]
        self._tz: str = _seeded_choice(_TIMEZONES, persona_id + "_tz")  # type: ignore[assignment]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._playwright = await async_playwright().start()

        cdp_url = self._settings.attach_cdp_url.strip()
        if cdp_url:
            # ── Attach mode: connect to the user's real running browser ──────
            # Uses the CDP protocol — works with both Firefox (96+) and Chrome.
            # The 'chromium' launcher here refers to the CDP protocol, not the engine.
            log.info("Attaching to running browser via CDP: %s", cdp_url)
            browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            # Open a fresh private tab so we don't clobber existing tabs
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            self._context = ctx
            self._page = await ctx.new_page()
            self._attached = True
            log.debug("Attached — opened new tab in real browser (PID unmanaged)")
        else:
            # ── Standalone mode: launch Playwright's own bundled browser ─────
            launcher = getattr(self._playwright, self._settings.browser_type)

            exe = self._settings.firefox_executable or ""
            if exe:
                log.debug("Using custom browser binary: %s", exe)

            # Seed persona profile from real Firefox profile on first use
            real_profile = self._settings.firefox_real_profile or ""
            if not real_profile and self._settings.browser_type == "firefox":
                real_profile = _find_firefox_real_profile()
            seed_persona_profile(self._profile_dir, real_profile)
            _clear_profile_locks(self._profile_dir)

            launch_kwargs: dict = {
                "headless": self._settings.headless,
                "slow_mo": self._settings.slow_mo_ms,
                "viewport": self._viewport,
                "user_agent": self._ua,
                "locale": "en-US",
                "timezone_id": self._tz,
                "permissions": ["geolocation", "notifications"],
                "java_script_enabled": True,
                "accept_downloads": False,
                "extra_http_headers": {
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                },
                "args": (
                    [
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-background-networking",
                        "--disable-client-side-phishing-detection",
                        "--disable-sync",
                        "--disable-translate",
                        "--metrics-recording-only",
                        "--safebrowsing-disable-auto-update",
                        "--password-store=basic",
                        "--use-mock-keychain",
                        "--disable-dev-shm-usage",
                        "--disable-extensions-except=",
                    ]
                    if self._settings.browser_type == "chromium"
                    else []
                ),
            }
            if self._settings.proxy_url:
                launch_kwargs["proxy"] = {"server": self._settings.proxy_url}
            if exe:
                launch_kwargs["executable_path"] = exe

            self._context = await launcher.launch_persistent_context(
                str(self._profile_dir),
                **launch_kwargs,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._context.add_init_script(_STEALTH_INIT_SCRIPT)
            await Stealth().apply_stealth_async(self._page)

        self._mouse_x = random.uniform(300, self._viewport["width"] - 300)
        self._mouse_y = random.uniform(200, self._viewport["height"] - 200)
        await self._page.mouse.move(self._mouse_x, self._mouse_y)
        log.debug("Browser ready — persona %s | attached=%s", self._persona_id[:8], self._attached)

    async def stop(self) -> None:
        try:
            if self._page:
                await self._page.close()
            # In attach mode we don't own the browser — only close our tab
            if not self._attached and self._context:
                await self._context.close()
        except Exception:
            pass
        if self._playwright:
            await self._playwright.stop()
        log.debug("Browser stopped%s", " (tab closed, real browser kept running)" if self._attached else f" — profile saved to {self._profile_dir}")

    # ── Low-level interaction primitives ───────────────────────────────────────

    async def _move_to(self, x: float, y: float) -> None:
        """Move mouse to (x, y) along a Bézier curve."""
        assert self._page
        start = Point(self._mouse_x, self._mouse_y)
        end = Point(x, y)
        path = generate_mouse_path(start, end)
        for pt in path:
            await self._page.mouse.move(pt.x, pt.y)
            await asyncio.sleep(random.uniform(0.002, 0.007))
        self._mouse_x, self._mouse_y = x, y

    async def _click(self, x: float, y: float) -> None:
        await self._move_to(x, y)
        await asyncio.sleep(random.uniform(0.02, 0.06))
        assert self._page
        await self._page.mouse.click(x, y)

    async def _type(self, text: str) -> None:
        """Type *text* with human-like per-character delays and hesitation pauses."""
        assert self._page
        for char in text:
            await self._page.keyboard.type(char, delay=typing_delay_ms())
            pause = occasional_pause_chance()
            if pause:
                await asyncio.sleep(pause)

    async def _scroll(self, direction: str = "down", steps: int = 3) -> None:
        assert self._page
        sign = -1 if direction == "up" else 1
        for _ in range(steps):
            delta = scroll_delta()
            await self._page.mouse.wheel(0, sign * delta)
            await asyncio.sleep(random.uniform(0.08, 0.25))

    # ── Action handlers ────────────────────────────────────────────────────────

    async def _act_search(self, query: str) -> None:
        assert self._page
        # Pick a search engine deterministically per-persona but with variety.
        # Weights approximate real-world market share.
        from urllib.parse import quote_plus
        engines = [
            ("Google",     f"https://www.google.com/search?q={quote_plus(query)}"),
            ("Google",     f"https://www.google.com/search?q={quote_plus(query)}"),
            ("Google",     f"https://www.google.com/search?q={quote_plus(query)}"),
            ("Bing",       f"https://www.bing.com/search?q={quote_plus(query)}"),
            ("DuckDuckGo", f"https://duckduckgo.com/?q={quote_plus(query)}&ia=web"),
            ("YouTube",    f"https://www.youtube.com/results?search_query={quote_plus(query)}"),
        ]
        # Use persona + query index for stable but varied selection
        idx = int(hashlib.md5((self._persona_id + query[:8]).encode()).hexdigest(), 16) % len(engines)
        engine_name, url = engines[idx]
        log.info("  🔍  Search [%s]: %s", engine_name, query)
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            log.warning("Search navigation failed: %s", exc)
        await human_sleep(0.5, 1.2)

    async def _act_navigate(self, url: str) -> None:
        assert self._page
        if not url.startswith("http"):
            url = "https://" + url
        log.info("  🌐  Navigate → %s", url)
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            log.warning("Navigation to %s timed out / failed: %s", url, exc)
        await human_sleep(0.5, 1.0)

    async def _act_click_link(self, target: Optional[str]) -> None:
        assert self._page
        if target:
            # Try as text match first, then as href fragment
            for locator in [
                self._page.get_by_text(target, exact=False),
                self._page.locator(f'a[href*="{target}"]'),
            ]:
                try:
                    if await locator.first.is_visible():
                        bb = await locator.first.bounding_box()
                        if bb:
                            log.info("  🖱️   Click link matching '%s'", target[:40])
                            await self._click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                            try:
                                await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
                            except Exception:
                                pass
                            return
                except Exception:
                    continue

        # Fallback: pick one of the first visible links on the page
        try:
            links = await self._page.locator("a:visible").all()
            visible = [l for l in links[:15] if await l.is_visible()]
            if visible:
                chosen = random.choice(visible)
                bb = await chosen.bounding_box()
                if bb:
                    log.info("  🖱️   Click random visible link")
                    await self._click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                    try:
                        await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    except Exception:
                        pass
        except Exception as exc:
            log.debug("click_link fallback failed: %s", exc)

    async def _act_scroll(self, description: str) -> None:
        direction = "up" if "up" in description.lower() else "down"
        log.info("  📜  Scroll %s", direction)
        await self._scroll(direction, steps=random.randint(2, 5))
        await human_sleep(0.2, 0.6)

    async def _act_read(self, dwell_min: float, dwell_max: float) -> None:
        log.info("  📖  Reading …")
        await self._scroll("down", steps=random.randint(1, 3))
        await human_sleep(dwell_min, dwell_max)

    async def _act_hover(self, target: Optional[str]) -> None:
        assert self._page
        if target:
            try:
                el = self._page.locator(target).first
                bb = await el.bounding_box()
                if bb:
                    await self._move_to(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                    await human_sleep(0.3, 1.2)
                    return
            except Exception:
                pass
        # Random hover within the visible area
        vp = self._page.viewport_size or {"width": 1280, "height": 800}
        await self._move_to(
            random.uniform(80, vp["width"] - 80),
            random.uniform(80, vp["height"] - 80),
        )
        await human_sleep(0.2, 0.8)

    async def _act_go_back(self) -> None:
        assert self._page
        log.info("  ⬅️   Go back")
        try:
            await self._page.go_back(wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            pass
        await human_sleep(0.4, 0.8)

    async def _act_idle(self, dwell_min: float, dwell_max: float) -> None:
        log.info("  ⏸️   Idle …")
        await human_sleep(dwell_min, dwell_max)

    async def _act_add_to_cart(self) -> None:
        assert self._page
        log.info("  🛒  Add to cart")
        cart_selectors = [
            'button:text-matches("add to cart", "i")',
            'button:text-matches("add to bag", "i")',
            'button:text-matches("buy now", "i")',
            '[data-action*="cart"]',
            '[id*="add-to-cart"]',
        ]
        for sel in cart_selectors:
            try:
                btn = self._page.locator(sel).first
                if await btn.is_visible():
                    bb = await btn.bounding_box()
                    if bb:
                        await self._click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                        await human_sleep(1.0, 2.5)
                        return
            except Exception:
                continue

    async def _act_fill_form(self, target: Optional[str], value: Optional[str]) -> None:
        if not target or not value:
            return
        assert self._page
        try:
            el = self._page.locator(target).first
            bb = await el.bounding_box()
            if bb:
                await self._click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            await self._type(value)
        except Exception as exc:
            log.debug("fill_form failed: %s", exc)

    # ── Plan execution ─────────────────────────────────────────────────────────

    async def execute_plan(self, plan: BrowsingPlan) -> int:
        """
        Execute every action in *plan*.
        Returns the number of successfully completed actions.
        """
        assert self._page, "Call start() before execute_plan()"
        completed = 0
        log.info(
            "▶  Executing plan '%s'  (%d actions)",
            plan.session_theme,
            len(plan.actions),
        )

        for i, action in enumerate(plan.actions, start=1):
            log.info("[%d/%d] %s", i, len(plan.actions), action.description)
            try:
                await self._dispatch(action)
                completed += 1
            except Exception as exc:
                log.warning("Action %d failed — skipping: %s", i, exc)

            # Brief inter-action gap (READ/IDLE/WATCH_VIDEO handle dwell internally)
            await human_sleep(0.3, 0.8)

        log.info("✔  Plan complete: %d/%d actions done", completed, len(plan.actions))
        return completed

    async def _dispatch(self, action: BrowsingAction) -> None:
        match action.type:
            case ActionType.SEARCH:
                await self._act_search(action.value or action.target or "")
            case ActionType.NAVIGATE:
                await self._act_navigate(action.target or "https://www.google.com")
            case ActionType.CLICK_LINK:
                await self._act_click_link(action.target)
            case ActionType.SCROLL:
                await self._act_scroll(action.description)
            case ActionType.READ:
                await self._act_read(action.dwell_min, action.dwell_max)
            case ActionType.HOVER:
                await self._act_hover(action.target)
            case ActionType.GO_BACK:
                await self._act_go_back()
            case ActionType.IDLE | ActionType.WATCH_VIDEO:
                await self._act_idle(action.dwell_min, action.dwell_max)
            case ActionType.ADD_TO_CART:
                await self._act_add_to_cart()
            case ActionType.FILL_FORM:
                await self._act_fill_form(action.target, action.value)
            case _:
                await human_sleep(1.0, 3.0)
