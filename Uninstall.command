#!/bin/bash
# Spotify → YouTube Music — macOS uninstaller
# Removes everything this app installed (venv, auth, checkpoints, Playwright cache).

cd "$(dirname "$0")"

echo ""
echo "  Spotify → YouTube Music — Uninstall"
echo "  ─────────────────────────────────────────"
echo ""

# .venv
if [ -d ".venv" ]; then
    echo "  Removing .venv/ …"
    rm -rf .venv
else
    echo "  .venv/ not found — skipping"
fi

# Auth file
if [ -f "headers_auth.json" ]; then
    echo "  Removing headers_auth.json …"
    rm -f headers_auth.json
else
    echo "  headers_auth.json not found — skipping"
fi

# Checkpoints
if [ -d "checkpoints" ]; then
    echo "  Removing checkpoints/ …"
    rm -rf checkpoints
else
    echo "  checkpoints/ not found — skipping"
fi

# Playwright Chromium cache (~150 MB)
PW_CACHE="$HOME/Library/Caches/ms-playwright"
if [ -d "$PW_CACHE" ]; then
    echo ""
    read -r -p "  Remove Playwright Chromium cache (~150 MB at $PW_CACHE)? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        echo "  Removing Playwright cache…"
        rm -rf "$PW_CACHE"
    else
        echo "  Skipping Playwright cache."
    fi
fi

echo ""
echo "  Done. You can now delete this folder."
echo ""
