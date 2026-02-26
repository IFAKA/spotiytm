"""
YouTube Music authentication.

Strategy (tried in order):

  1. browser_cookie3 — reads & decrypts cookies directly from the Brave/Chrome
     SQLite database using Python + macOS Keychain. Instant, no browser window,
     works even when Brave is running.

  2. Playwright bundled Chromium — opens a fresh browser window, user signs in
     to Google once (~30 sec), headers are captured automatically. Used only if
     browser_cookie3 can't find valid YouTube Music cookies.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

HEADERS_FILE = "headers_auth.json"

_AUTH_COOKIES = ("SAPISID", "__Secure-3PAPISID", "SSID")

# True while a Playwright browser window is open for sign-in
playwright_active: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def is_connected() -> bool:
    p = Path(HEADERS_FILE)
    return p.exists() and p.stat().st_size > 10


async def validate_auth(yt) -> bool:
    """
    Make a lightweight test request to confirm YT Music credentials are still valid.
    Uses get_library_playlists (requires auth) rather than search (public endpoint).
    Deletes headers_auth.json and returns False on auth errors (401/403).
    Raises on non-auth errors so callers can propagate them.
    """
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: yt.get_library_playlists(limit=1)
        )
        return True
    except Exception as e:
        msg = str(e)
        if any(code in msg for code in ("401", "403", "UNAUTHENTICATED")):
            Path(HEADERS_FILE).unlink(missing_ok=True)
            return False
        raise


async def capture_headers_via_browser() -> None:
    """
    Obtain YouTube Music auth headers and write headers_auth.json.
    Tries cookie extraction first; falls back to Playwright sign-in.
    """
    # ── Path 1: read cookies directly (instant) ────────────────────────────
    cookie_str = _extract_cookies_from_browser()
    if cookie_str:
        _write_headers_json(cookie_str)
        return

    # ── Path 2: Playwright sign-in (one-time ~30 sec) ──────────────────────
    await _capture_via_playwright()


# ──────────────────────────────────────────────────────────────────────────────
# Path 1 — browser_cookie3
# ──────────────────────────────────────────────────────────────────────────────

def _extract_cookies_from_browser() -> str | None:
    """
    Use browser_cookie3 to read & decrypt YouTube cookies from the local
    Brave or Chrome profile. Returns a cookie string or None.
    """
    try:
        import browser_cookie3
    except ImportError:
        return None

    loaders = []
    if sys.platform == "win32":
        try:
            loaders.append(browser_cookie3.edge)
        except AttributeError:
            pass
    try:
        loaders.append(browser_cookie3.brave)
    except AttributeError:
        pass
    try:
        loaders.append(browser_cookie3.chrome)
    except AttributeError:
        pass

    for load in loaders:
        try:
            jar = load(domain_name=".youtube.com")
            cookies = {c.name: c.value for c in jar}
            if any(name in cookies for name in _AUTH_COOKIES):
                return "; ".join(f"{k}={v}" for k, v in cookies.items())
        except Exception as e:
            print(f"[auth] browser_cookie3 ({load.__name__}): {e}")

    return None


def _sapisid_hash(sapisid: str, origin: str = "https://music.youtube.com") -> str:
    """Compute the SAPISIDHASH authorization value ytmusicapi expects."""
    import hashlib, time as _time
    ts = str(int(_time.time()))
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def _write_headers_json(cookie_str: str) -> None:
    """Write a minimal headers_auth.json that ytmusicapi will accept."""
    # Extract SAPISID (or __Secure-3PAPISID) from the cookie string so we can
    # generate the Authorization header that ytmusicapi v1.9+ requires to
    # identify this as browser-type auth (AuthType.BROWSER).
    sapisid = ""
    for part in cookie_str.split(";"):
        name, _, value = part.strip().partition("=")
        if name in ("__Secure-3PAPISID", "SAPISID"):
            sapisid = value
            if name == "__Secure-3PAPISID":
                break  # prefer this one

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Type": "application/json",
        "X-Goog-AuthUser": "0",
        "x-origin": "https://music.youtube.com",
        "Cookie": cookie_str,
    }
    if sapisid:
        headers["Authorization"] = _sapisid_hash(sapisid)

    with open(HEADERS_FILE, "w") as f:
        json.dump(headers, f, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# Path 2 — Playwright sign-in
# ──────────────────────────────────────────────────────────────────────────────

async def _capture_via_playwright() -> None:
    """
    Launch a fresh Playwright Chromium window, navigate to music.youtube.com,
    wait for the user to sign in, capture the first authenticated request headers.
    """
    global playwright_active
    from playwright.async_api import async_playwright

    captured: dict = {}
    ready = asyncio.Event()

    async with async_playwright() as pw:
        launch_args = ["--no-first-run", "--no-default-browser-check"]
        try:
            browser = await pw.chromium.launch(headless=False, args=launch_args)
        except Exception:
            import subprocess
            print("[auth] Installing Playwright Chromium (one-time, ~150 MB)...")
            subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            browser = await pw.chromium.launch(headless=False, args=launch_args)

        playwright_active = True
        context = await browser.new_context()
        page = await context.new_page()

        async def handle_request(request):
            if ready.is_set() or "music.youtube.com" not in request.url:
                return
            try:
                headers = await request.all_headers()
            except Exception:
                headers = dict(request.headers)
            if any(c in headers.get("cookie", "") for c in _AUTH_COOKIES):
                captured.update(headers)
                ready.set()

        page.on("request", handle_request)
        await page.goto("https://music.youtube.com")

        try:
            await asyncio.wait_for(ready.wait(), timeout=300)
        except asyncio.TimeoutError:
            await browser.close()
            playwright_active = False
            raise RuntimeError("Timed out waiting for sign-in (5 min limit).")

        await browser.close()
        playwright_active = False

    if not captured:
        raise RuntimeError("No authenticated headers captured.")

    cookie_str = captured.get("cookie", "")
    if not cookie_str:
        raise RuntimeError("Captured headers had no cookie field.")

    _write_headers_json(cookie_str)
