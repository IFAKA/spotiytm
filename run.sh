#!/bin/bash
cd "$(dirname "$0")"

VENV=".venv"
EXPECTED_VENV_PATH="$(pwd)/$VENV"
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
DIM="\033[2m"
RESET="\033[0m"

ok()   { echo -e "  ${GREEN}✓${RESET}  $1"; }
step() { echo -e "  ${BOLD}$1${RESET}"; }
fail() { echo -e "\n  ${RED}✗  Error: $1${RESET}\n"; exit 1; }
venv_ok() {
  [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import sys" >/dev/null 2>&1 || return 1
  if [ -f "$VENV/pyvenv.cfg" ] && grep -q "^command = " "$VENV/pyvenv.cfg"; then
    grep -Fq "$EXPECTED_VENV_PATH" "$VENV/pyvenv.cfg"
  fi
}

echo ""
echo -e "  ${BOLD}Spotify → YouTube Music${RESET}"
echo -e "  ${DIM}───────────────────────────────${RESET}"
echo ""

# ── 1. Python ──────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  fail "python3 not found. Install it from https://www.python.org or via: brew install python"
fi

PYTHON_VERSION=$(python3 --version 2>&1)
ok "Found $PYTHON_VERSION"

# ── 2. Virtual environment ─────────────────────────────
if [ -d "$VENV" ] && ! venv_ok; then
  step "Rebuilding virtual environment..."
  rm -rf "$VENV" || fail "Could not remove broken virtual environment"
fi

if [ ! -d "$VENV" ]; then
  step "Creating virtual environment..."
  python3 -m venv "$VENV" || fail "Could not create virtual environment"
  ok "Virtual environment created (.venv)"
else
  ok "Virtual environment ready (.venv)"
fi

# ── 3. Dependencies ────────────────────────────────────
step "Installing dependencies..."
PIP_OUTPUT=$("$VENV/bin/python" -m pip install -r requirements.txt \
  --quiet \
  --disable-pip-version-check \
  2>&1)
PIP_EXIT=$?
# Strip blank lines and pip notice spam
CLEANED=$(echo "$PIP_OUTPUT" | grep -v "^[[:space:]]*$" | grep -v "\[notice\]")
if [ $PIP_EXIT -ne 0 ]; then
  echo ""
  echo -e "  ${RED}pip output:${RESET}"
  echo "$CLEANED" | sed 's/^/    /'
  echo ""
  fail "Dependency installation failed (see above)"
fi

ok "All dependencies installed"

# ── 4. Start ───────────────────────────────────────────
echo ""
echo -e "  ${GREEN}${BOLD}Opening http://localhost:3000 …${RESET}"
echo -e "  ${DIM}Press Ctrl+C to stop${RESET}"
echo ""

exec "$VENV/bin/python" app.py
