"""
Conversion orchestrator.

Streams Server-Sent Events for real-time progress.
Supports checkpoint resume: saves progress to checkpoint_{playlist_id}.json
so that if the same URL is converted again, already-found tracks are skipped.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import AsyncIterator

from .spotify import Track, fetch_playlist
from .ytmusic import (
    YTMusic,
    add_tracks_to_playlist,
    create_playlist,
    search_track,
)

CHECKPOINT_DIR = "checkpoints"
CONCURRENCY = 5
CHECKPOINT_INTERVAL = 10

_sse = lambda d: f"data: {json.dumps(d)}\n\n"
_log = lambda msg: _sse({"type": "log", "message": msg})


def _checkpoint_path(spotify_id: str) -> str:
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    return os.path.join(CHECKPOINT_DIR, f"checkpoint_{spotify_id}.json")


def _load_checkpoint(spotify_id: str) -> dict:
    path = _checkpoint_path(spotify_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_checkpoint(spotify_id: str, data: dict) -> None:
    path = _checkpoint_path(spotify_id)
    with open(path, "w") as f:
        json.dump(data, f)


async def convert_stream(spotify_url: str, yt: YTMusic) -> AsyncIterator[str]:
    """
    Async generator that yields SSE-formatted strings.

    Event types:
      fetching  — started fetching Spotify data
      fetched   — playlist info available
      log       — debug/progress message
      track     — one track result (found/missing)
      done      — conversion complete
      error     — something went wrong
    """
    m = re.search(r"playlist/([A-Za-z0-9]+)", spotify_url)
    spotify_id = m.group(1) if m else "unknown"

    yield _sse({"type": "fetching"})

    # --- Fetch Spotify tracks ---
    try:
        playlist_name, tracks = await fetch_playlist(spotify_url)
    except Exception as exc:
        yield _sse({"type": "error", "message": f"Spotify fetch failed: {exc}"})
        return

    total = len(tracks)
    yield _sse({"type": "fetched", "name": playlist_name, "total": total})
    yield _log(f'Fetched "{playlist_name}" — {total} tracks from Spotify')

    # --- Load checkpoint ---
    checkpoint = _load_checkpoint(spotify_id)
    yt_playlist_id: str | None = checkpoint.get("playlistId")
    cached: dict[str, str | None] = checkpoint.get("results", {})  # track_key -> videoId | None

    # Track which videoIds were already added in a previous session
    cached_video_ids: set[str] = {v for v in cached.values() if v}

    if yt_playlist_id:
        yield _log(
            f"Resuming from checkpoint: {len(cached_video_ids)} tracks already added, "
            f"playlist {yt_playlist_id}, {len(cached) - len(cached_video_ids)} previously missing"
        )
    else:
        yield _log("No checkpoint — starting fresh")

    # --- Create (or reuse) YTMusic playlist ---
    if not yt_playlist_id:
        try:
            yt_playlist_id = await create_playlist(
                yt,
                name=f"{playlist_name} (from Spotify)",
                description=f"Converted from Spotify: {spotify_url}",
            )
            checkpoint = {"playlistId": yt_playlist_id, "results": cached}
            _save_checkpoint(spotify_id, checkpoint)
            yield _log(f"Created YouTube Music playlist: {yt_playlist_id}")
        except Exception as exc:
            msg = str(exc)
            if any(code in msg for code in ("401", "403", "Unauthorized", "UNAUTHENTICATED")):
                from pathlib import Path
                Path("headers_auth.json").unlink(missing_ok=True)
                yield _sse({"type": "error", "message": "YouTube Music credentials expired. Please reconnect."})
            else:
                yield _sse({"type": "error", "message": f"Could not create playlist: {exc}"})
            return
    else:
        yield _log(f"Reusing existing YouTube Music playlist: {yt_playlist_id}")

    # --- Parallel search with semaphore ---
    sem = asyncio.Semaphore(CONCURRENCY)

    cached_count = len(cached)
    new_to_search = total - cached_count
    if new_to_search > 0:
        yield _log(f"Searching {new_to_search} tracks on YouTube Music ({CONCURRENCY} concurrent)…")
    else:
        yield _log(f"All {total} tracks already searched (from checkpoint)")

    async def bounded_search(i: int, t: Track) -> tuple[int, Track, str | None]:
        key = f"{t.artists}||{t.name}"
        if key in cached:
            return i, t, cached[key]  # resume: already searched
        async with sem:
            vid = await search_track(yt, t.name, t.artists)
        cached[key] = vid
        return i, t, vid

    tasks = [asyncio.ensure_future(bounded_search(i, t)) for i, t in enumerate(tracks)]

    # (original_index, video_id) — collected to preserve Spotify track order
    ordered_new: list[tuple[int, str]] = []
    missing_tracks: list[dict] = []
    completed = 0

    # Stream results as they complete (UI order = search completion order)
    for coro in asyncio.as_completed(tasks):
        try:
            idx, track, video_id = await coro
        except Exception:
            completed += 1
            yield _sse({
                "type": "track",
                "i": completed,
                "total": total,
                "name": "Unknown",
                "artists": "",
                "status": "missing",
            })
            continue

        completed += 1
        status = "found" if video_id else "missing"

        event: dict = {
            "type": "track",
            "i": completed,
            "total": total,
            "name": track.name,
            "artists": track.artists,
            "status": status,
        }
        if video_id:
            event["videoId"] = video_id
            if video_id not in cached_video_ids:
                ordered_new.append((idx, video_id))
        else:
            missing_tracks.append({"name": track.name, "artists": track.artists})

        yield _sse(event)

        # Persist checkpoint every CHECKPOINT_INTERVAL tracks
        if completed % CHECKPOINT_INTERVAL == 0:
            checkpoint["results"] = cached
            _save_checkpoint(spotify_id, checkpoint)

    # Final checkpoint write
    checkpoint["results"] = cached
    _save_checkpoint(spotify_id, checkpoint)

    total_found = len(ordered_new) + len(cached_video_ids)
    yield _log(
        f"Search complete: {total_found} found total "
        f"({len(ordered_new)} new + {len(cached_video_ids)} from cache), "
        f"{len(missing_tracks)} not found on YouTube Music"
    )

    # Sort by original Spotify playlist position before adding to YT Music
    ordered_new.sort(key=lambda x: x[0])
    # Deduplicate while preserving order (multiple Spotify tracks may resolve to the same videoId)
    seen: set[str] = set()
    new_video_ids: list[str] = []
    for _, vid in ordered_new:
        if vid not in seen:
            seen.add(vid)
            new_video_ids.append(vid)

    # --- Add only newly-found tracks to the playlist ---
    if new_video_ids:
        batch_size = 50
        n_batches = (len(new_video_ids) + batch_size - 1) // batch_size
        yield _log(f"Adding {len(new_video_ids)} new tracks in {n_batches} batch(es)…")
        try:
            for i in range(0, len(new_video_ids), batch_size):
                batch_num = i // batch_size + 1
                batch = new_video_ids[i : i + batch_size]
                yield _log(f"  Batch {batch_num}/{n_batches}: {len(batch)} tracks")
                await add_tracks_to_playlist(yt, yt_playlist_id, batch)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"Error adding tracks to playlist: {exc}"})
            return
    else:
        yield _log("No new tracks to add (all already in playlist or none found)")

    found_count = len(new_video_ids) + len(cached_video_ids)
    yield _sse({
        "type": "done",
        "playlistId": yt_playlist_id,
        "found": found_count,
        "missing": len(missing_tracks),
        "missingTracks": missing_tracks,
    })

    # Clear checkpoint on successful completion so next run starts fresh
    try:
        os.remove(_checkpoint_path(spotify_id))
    except FileNotFoundError:
        pass
