#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# chrome-debug.sh  —  Launch Chrome with remote debugging enabled
#
# Chrome blocks CDP on its DEFAULT profile dir (~/.config/google-chrome).
# This script syncs your real profile to a non-default dir so CDP works
# AND you keep your real cookies/sessions/identity.
#
# USAGE
#   ./chrome-debug.sh              # real profile (synced copy)
#   ./chrome-debug.sh --sync       # force re-sync from real profile first
#   ./chrome-debug.sh --fresh      # temp profile (no cookies, safe test)
#   ./chrome-debug.sh --port 9333  # custom port
#   ./chrome-debug.sh --no-kill    # don't kill existing Chrome
#
# WORKFLOW
#   1. Run ./chrome-debug.sh  (keeps running, leave it open)
#   2. In another terminal: i-fake run-once --endless
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CHROME_BIN="${CHROME_BIN:-$(command -v google-chrome 2>/dev/null || command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null || echo "")}"
DEBUG_PORT=9222
# Source = your real Chrome data dir (CDP is BLOCKED here by Chrome)
REAL_PROFILE_SRC="$HOME/.config/google-chrome"
# Dest  = non-default dir (CDP is ALLOWED here) — synced copy of real profile
REAL_PROFILE_CDP="$HOME/.config/google-chrome-cdp"
FRESH_PROFILE="/tmp/chrome-cdp-fresh"
USE_FRESH=false
KILL_EXISTING=true
FORCE_SYNC=false

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh)    USE_FRESH=true ;;
        --sync)     FORCE_SYNC=true ;;
        --port)     DEBUG_PORT="$2"; shift ;;
        --no-kill)  KILL_EXISTING=false ;;
        --help|-h)
            grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \?//'
            exit 0 ;;
    esac
    shift
done

if [[ -z "$CHROME_BIN" ]]; then
    echo "ERROR: Could not find google-chrome or chromium. Set CHROME_BIN env var." >&2
    exit 1
fi

# ── Kill existing Chrome (required so new instance can bind the port) ─────────
if $KILL_EXISTING; then
    if pgrep -f "/opt/google/chrome/chrome\b" > /dev/null 2>&1 || \
       pgrep -f "chromium.*--type=browser" > /dev/null 2>&1; then
        echo "⚠  Killing existing Chrome/Chromium processes…"
        pkill -f "/opt/google/chrome/chrome" 2>/dev/null || true
        pkill -f "chromium" 2>/dev/null || true
        sleep 2
        echo "✓  Done."
    fi
fi

# ── Pick / prepare profile dir ────────────────────────────────────────────────
if $USE_FRESH; then
    PROFILE_DIR="$FRESH_PROFILE"
    rm -rf "$PROFILE_DIR"
    mkdir -p "$PROFILE_DIR"
    echo "ℹ  Using fresh temporary profile: $PROFILE_DIR"
else
    PROFILE_DIR="$REAL_PROFILE_CDP"

    # Sync real profile → CDP dir on first run OR when --sync is passed
    NEEDS_SYNC=false
    [[ ! -d "$PROFILE_DIR/Default" ]] && NEEDS_SYNC=true
    $FORCE_SYNC && NEEDS_SYNC=true

    if $NEEDS_SYNC; then
        if [[ ! -d "$REAL_PROFILE_SRC/Default" ]]; then
            echo "⚠  Real Chrome profile not found at $REAL_PROFILE_SRC — using fresh profile."
            PROFILE_DIR="$FRESH_PROFILE"
            mkdir -p "$PROFILE_DIR"
        else
            echo "📋 Syncing real Chrome profile → $PROFILE_DIR"
            echo "   (skipping caches — this is fast)"
            mkdir -p "$PROFILE_DIR"
            rsync -a --delete \
                --exclude='*Cache*' \
                --exclude='*cache*' \
                --exclude='GPUCache' \
                --exclude='Code Cache' \
                --exclude='Crash Reports' \
                --exclude='CrashpadMetrics*' \
                --exclude='*.log' \
                --exclude='lockfile' \
                "$REAL_PROFILE_SRC/Default" \
                "$PROFILE_DIR/" 2>/dev/null || {
                    echo "  rsync not available, falling back to cp…"
                    cp -r "$REAL_PROFILE_SRC/Default" "$PROFILE_DIR/"
                }
            # Local State holds general Chrome preferences
            [[ -f "$REAL_PROFILE_SRC/Local State" ]] && \
                cp "$REAL_PROFILE_SRC/Local State" "$PROFILE_DIR/"
            echo "✓  Profile synced. Run with --sync to refresh again later."
        fi
    else
        echo "ℹ  Using existing CDP profile at $PROFILE_DIR"
        echo "   (run with --sync to refresh cookies from real Chrome)"
    fi
fi

# ── Launch Chrome with debug port ─────────────────────────────────────────────
echo ""
echo "🚀 Launching Chrome with --remote-debugging-port=$DEBUG_PORT"
echo "   Binary:  $CHROME_BIN"
echo "   Profile: $PROFILE_DIR"
echo ""
echo "   i-fake will connect via: http://localhost:$DEBUG_PORT"
echo "   Keep this terminal open while i-fake runs. Ctrl-C to stop."
echo ""

CHROME_LOG="/tmp/chrome-debug.log"
echo "   Chrome logs → $CHROME_LOG"
echo ""

exec "$CHROME_BIN" \
    --remote-debugging-port="$DEBUG_PORT" \
    --remote-allow-origins='*' \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --disable-extensions \
    "$@" 2>"$CHROME_LOG"
