"""
YouTube Music helpers: search and playlist management via ytmusicapi.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ytmusicapi import YTMusic


def get_ytmusic(auth_path: str = "headers_auth.json") -> YTMusic:
    """Return an authenticated YTMusic instance."""
    return YTMusic(auth_path)


def _run(fn):
    return asyncio.get_running_loop().run_in_executor(None, fn)


async def search_track(
    yt: YTMusic,
    name: str,
    artists: str,
) -> Optional[str]:
    """
    Two-stage search:
      1. Filter by 'songs' (most accurate).
      2. Unfiltered fallback.

    Returns videoId or None.
    """
    query = f"{artists} {name}".strip()

    # Stage 1: songs filter
    try:
        results = await _run(lambda: yt.search(query, filter="songs", limit=3))
        if results:
            return results[0].get("videoId")
    except Exception:
        pass

    # Stage 2: unfiltered fallback
    try:
        results = await _run(lambda: yt.search(query, limit=5))
        for r in results:
            vid = r.get("videoId")
            if vid:
                return vid
    except Exception:
        pass

    return None


async def create_playlist(yt: YTMusic, name: str, description: str = "") -> str:
    """Create a new YTMusic playlist and return its playlistId."""
    result = await _run(lambda: yt.create_playlist(name, description))
    if isinstance(result, str):
        return result
    return result.get("playlistId", result)


async def add_tracks_to_playlist(
    yt: YTMusic,
    playlist_id: str,
    video_ids: list[str],
) -> None:
    """Add a list of videoIds to an existing playlist."""
    if not video_ids:
        return
    await _run(lambda: yt.add_playlist_items(playlist_id, video_ids, duplicates=True))
