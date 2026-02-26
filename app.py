"""
app.py — Entry point for Spotify → YouTube Music Converter

Run via:  ./run.sh   (handles venv + deps automatically)
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import threading
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Spotify → YouTube Music")

# Static files & templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------- Auth ----------

# Stores progress / error / running task from the background auth task
_auth_state: dict = {"error": None, "status": None, "task": None}

# validate_auth result is cached to avoid a live YT search on every conversion
_VALIDATE_TTL = 300  # seconds
_auth_validated_at: float = 0.0


@app.get("/api/auth/status")
async def auth_status():
    from backend.auth import is_connected, playwright_active as _pw_active
    return {"connected": is_connected(), "error": _auth_state["error"], "status": _auth_state["status"], "playwrightActive": _pw_active}


@app.post("/api/auth/start")
async def auth_start():
    """Read Brave cookies or open a sign-in browser, save headers_auth.json."""
    from backend.auth import capture_headers_via_browser, is_connected

    if is_connected():
        return {"status": "already_connected"}

    _auth_state["error"] = None
    _auth_state["status"] = "Reading cookies from your browser…"

    async def _run():
        try:
            await capture_headers_via_browser()
            _auth_state["status"] = "Connected!"
        except Exception as e:
            _auth_state["error"] = str(e)
            _auth_state["status"] = None
            print(f"[auth] {e}")
        finally:
            _auth_state["task"] = None

    _auth_state["task"] = asyncio.create_task(_run())
    return {"status": "started"}


@app.post("/api/auth/cancel")
async def auth_cancel():
    """Cancel an in-progress auth attempt."""
    task = _auth_state.get("task")
    if task and not task.done():
        task.cancel()
    _auth_state["status"] = None
    _auth_state["error"] = None
    _auth_state["task"] = None
    return {"status": "cancelled"}


# ---------- Spotify ----------

@app.get("/api/spotify")
async def spotify_info(url: str):
    """Return playlist name and track list (for preview, not used by SSE flow)."""
    from backend.spotify import fetch_playlist
    try:
        name, tracks = await fetch_playlist(url)
        return {
            "name": name,
            "total": len(tracks),
            "tracks": [{"name": t.name, "artists": t.artists} for t in tracks],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Convert (SSE) ----------

@app.get("/api/convert")
async def convert(url: str):
    """
    Server-Sent Events stream.
    Fetches Spotify playlist, searches YouTube Music, creates playlist.

    Pre-flight errors are yielded as SSE error events rather than raised as
    HTTPException — EventSource can't read a non-2xx response body, so any
    raise here would silently appear as "Connection lost" in the UI.
    """
    if not url:
        raise HTTPException(status_code=400, detail="url parameter is required")

    from backend.auth import is_connected, validate_auth
    from backend.convert import convert_stream
    from backend.ytmusic import get_ytmusic

    def _sse_err(msg: str) -> str:
        return f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

    async def event_generator() -> AsyncIterator[str]:
        global _auth_validated_at

        # Pre-flight: auth file present?
        if not is_connected():
            yield _sse_err("YouTube Music not connected. Please reconnect.")
            return

        # Pre-flight: load credentials
        try:
            yt = get_ytmusic()
        except Exception as e:
            yield _sse_err(f"Could not load YouTube Music credentials: {e}")
            return

        # Pre-flight: validate credentials (with TTL cache)
        now = time.monotonic()
        if now - _auth_validated_at > _VALIDATE_TTL:
            try:
                valid = await validate_auth(yt)
            except Exception as e:
                yield _sse_err(f"YouTube Music auth check failed: {e}")
                return
            if not valid:
                yield _sse_err("YouTube Music credentials expired. Please reconnect.")
                return
            _auth_validated_at = now

        try:
            async for chunk in convert_stream(url, yt):
                yield chunk
        except asyncio.CancelledError:
            pass  # client disconnected

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def _find_port(start: int = 3000, attempts: int = 10) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found between {start}–{start + attempts - 1}")


PORT = _find_port()


def _open_browser():
    import time, webbrowser
    time.sleep(1.2)  # wait for server to be ready
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    print(f"  →  Starting on http://localhost:{PORT}")
    thread = threading.Thread(target=_open_browser, daemon=True)
    thread.start()

    try:
        uvicorn.run(
            "app:app",
            host="127.0.0.1",
            port=PORT,
            reload=False,
            log_level="warning",
        )
    except KeyboardInterrupt:
        print("\n\n  Stopped. Bye!\n")
