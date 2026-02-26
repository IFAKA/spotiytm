"""
Spotify playlist scraper.

Primary: scrapes open.spotify.com/embed/ (no auth needed)
Fallback: uses Spotify Web API if SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET are set in .env

NOTE (Feb 2026): Spotify's Web API now restricts playlist items to playlists the
user owns or collaborates on when using Client Credentials. The official API
fallback (_fetch_via_api) therefore no longer works for arbitrary public playlists.
The embed scraper is the only credential-free path.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

EMBED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Track:
    name: str
    artists: str


def _extract_playlist_id(url: str) -> str:
    m = re.search(r"playlist/([A-Za-z0-9]+)", url)
    if not m:
        raise ValueError(f"Could not find playlist ID in URL: {url}")
    return m.group(1)


# ---------------------------------------------------------------------------
# Shared HTML parser
# ---------------------------------------------------------------------------

def _parse_next_data(html: str, playlist_id: str) -> tuple[str, list[Track]]:
    """Extract playlist name and tracks from a Spotify embed page HTML string."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        raise RuntimeError("Could not find __NEXT_DATA__ in Spotify embed page")

    data = json.loads(m.group(1))

    # Navigate to the entity data — structure may vary slightly, try both paths
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except KeyError:
        # Alternative path used in some embed versions
        try:
            entity = data["props"]["pageProps"]["initialStoreState"]["entities"]["playlists"][playlist_id]
        except KeyError:
            raise RuntimeError(
                "Spotify embed page structure changed — could not parse track list. "
                "Set SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in .env to use the official API."
            )

    playlist_name: str = entity.get("name", "Spotify Playlist")
    raw_tracks: list[dict] = entity.get("trackList", [])

    tracks: list[Track] = []
    for t in raw_tracks:
        title = t.get("title") or t.get("name", "")
        subtitle = t.get("subtitle") or t.get("artists", "")
        if title:
            tracks.append(Track(name=title, artists=subtitle))

    if not tracks:
        raise RuntimeError(
            "Scraped embed page but found 0 tracks. "
            "The playlist may be empty or the page structure changed."
        )

    return playlist_name, tracks


# ---------------------------------------------------------------------------
# Primary: embed scrape — fast HTTP path (works for playlists ≤ ~100 tracks)
# ---------------------------------------------------------------------------

async def _fetch_via_embed_http(playlist_id: str) -> tuple[str, list[Track]]:
    """Single HTTP GET of the embed page; only returns the initial ~100 tracks."""
    embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(embed_url, headers=EMBED_HEADERS)
        resp.raise_for_status()
    return _parse_next_data(resp.text, playlist_id)


async def _fetch_via_webplayer(playlist_id: str) -> tuple[str, list[Track]]:
    """
    Load the full Spotify web player page (not embed) and intercept
    api-partner.spotify.com GraphQL responses to collect all tracks.

    The embed is hard-capped at 100 tracks in __NEXT_DATA__. The web player
    paginates through every track via its partner API and reports totalCount,
    so this path works for playlists of any length.
    """
    from playwright.async_api import async_playwright

    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"

    collected: dict[int, Track] = {}   # absolute_position -> Track
    playlist_name = ""
    total_count = 0
    seen: set[tuple] = set()  # (operationName, offset) — avoids cross-op collisions

    def _ingest(content: dict, base_offset: int) -> None:
        nonlocal total_count
        if not content:
            return
        if content.get("totalCount") and not total_count:
            total_count = content["totalCount"]
        for i, item in enumerate(content.get("items") or []):
            td = ((item.get("itemV2") or {}).get("data")) or {}
            name = td.get("name", "")
            if not name:
                continue
            artists = ", ".join(
                (a.get("profile") or {}).get("name", "")
                for a in (td.get("artists") or {}).get("items", [])
                if (a.get("profile") or {}).get("name")
            )
            collected[base_offset + i] = Track(name=name, artists=artists)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        async def on_response(response):
            nonlocal playlist_name
            if "api-partner.spotify.com" not in response.url:
                return
            try:
                req_body = json.loads(response.request.post_data or "{}")
                op = req_body.get("operationName", "")
                offset = req_body.get("variables", {}).get("offset", 0)
                key = (op, offset)
                if key in seen:
                    return
                seen.add(key)
                body = await response.json()
                pl = (body.get("data") or {}).get("playlistV2") or {}
                if pl.get("name") and not playlist_name:
                    playlist_name = pl["name"]
                _ingest(pl.get("content") or {}, offset)
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(playlist_url, wait_until="networkidle")

        # Scroll with mouse wheel (triggers Spotify's lazy-loading)
        await page.mouse.move(640, 400)
        stale = 0
        prev = 0
        for _ in range(200):
            if total_count and len(collected) >= total_count:
                break
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(500)
            cur = len(collected)
            if cur == prev:
                stale += 1
                if stale >= 8:
                    break
            else:
                stale = 0
            prev = cur

        await browser.close()

    if not collected:
        return await _fetch_via_embed_http(playlist_id)

    return playlist_name or "Spotify Playlist", [collected[k] for k in sorted(collected)]


async def _fetch_via_embed(playlist_id: str) -> tuple[str, list[Track]]:
    """
    Scrape the Spotify embed page for track data (no credentials required).

    Uses a fast HTTP GET first. If the result contains ≥100 tracks (the embed
    hard-cap), falls back to the full web player which paginates via the
    partner API and works for playlists of any length.
    """
    name, tracks = await _fetch_via_embed_http(playlist_id)

    if len(tracks) >= 100:
        return await _fetch_via_webplayer(playlist_id)

    return name, tracks


# ---------------------------------------------------------------------------
# Fallback: official Spotify API (Client Credentials)
#
# NOTE (Feb 2026): This no longer works for public playlists you don't own.
# Spotify now requires the playlist owner's OAuth token to read track items.
# Only use this if you own/collaborate on the target playlist.
# ---------------------------------------------------------------------------

async def _get_spotify_token() -> str:
    import base64
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {creds}"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def _fetch_via_api(playlist_id: str) -> tuple[str, list[Track]]:
    token = await _get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}
    tracks: list[Track] = []
    playlist_name = "Spotify Playlist"

    async with httpx.AsyncClient(timeout=30) as client:
        # Fetch playlist metadata
        meta = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers=headers,
            params={"fields": "name"},
        )
        meta.raise_for_status()
        playlist_name = meta.json().get("name", playlist_name)

        # Paginate through all tracks
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        params: dict = {"limit": 100, "fields": "next,items(track(name,artists(name)))"}
        while url:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            body = resp.json()
            for item in body.get("items", []):
                track = item.get("track")
                if track:
                    name = track.get("name", "")
                    artists = ", ".join(a["name"] for a in track.get("artists", []))
                    if name:
                        tracks.append(Track(name=name, artists=artists))
            url = body.get("next")
            params = {}  # next URL already has params encoded

    return playlist_name, tracks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_playlist(url: str) -> tuple[str, list[Track]]:
    """Return (playlist_name, tracks) for a Spotify playlist URL."""
    playlist_id = _extract_playlist_id(url)

    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        return await _fetch_via_api(playlist_id)

    return await _fetch_via_embed(playlist_id)
