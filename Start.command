#!/bin/bash
# Spotify → YouTube Music — macOS launcher
# Double-click to run. First time: right-click → Open (Gatekeeper step).

cd "$(dirname "$0")"

# ── Python check ────────────────────────────────────────────────────────────
PYTHON=""
if command -v python3 &>/dev/null; then
    # Detect the Xcode stub (prints "xcrun: error" to stderr, no real Python)
    PY_TEST=$(python3 --version 2>&1)
    if echo "$PY_TEST" | grep -q "xcrun"; then
        osascript <<'APPLESCRIPT'
tell application "System Events"
    set result to button returned of (display dialog "Python is not installed. The macOS stub requires 3 GB of Xcode tools.\n\nDownload the real Python from python.org?" buttons {"Cancel", "Open Download Page"} default button "Open Download Page" with icon caution)
    if result is "Open Download Page" then
        do shell script "open https://www.python.org/downloads/macos/"
    end if
end tell
APPLESCRIPT
        exit 1
    fi
    PYTHON="python3"
fi

if [ -z "$PYTHON" ]; then
    osascript <<'APPLESCRIPT'
tell application "System Events"
    set result to button returned of (display dialog "Python is not installed.\n\nDownload it from python.org to run this app." buttons {"Cancel", "Open Download Page"} default button "Open Download Page" with icon caution)
    if result is "Open Download Page" then
        do shell script "open https://www.python.org/downloads/macos/"
    end if
end tell
APPLESCRIPT
    exit 1
fi

echo ""
echo "  Spotify → YouTube Music"
echo "  ────────────────────────────────────────"
echo ""

# ── Step 1: Virtual environment ──────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "  Step 1/3: Creating environment (first time only)…"
    $PYTHON -m venv .venv
else
    echo "  Step 1/3: Environment ready ✓"
fi

source .venv/bin/activate

# ── Step 2: Dependencies ─────────────────────────────────────────────────────
echo "  Step 2/3: Installing tools (first time: ~2 min)…"
pip install -r requirements.txt --quiet

# ── Step 3: Launch ───────────────────────────────────────────────────────────
echo "  Step 3/3: Starting app — your browser will open automatically"
echo ""
echo "  ─────────────────────────────────────────"
echo "  Keep this window open. Close it to stop the app."
echo "  ─────────────────────────────────────────"
echo ""

python app.py
