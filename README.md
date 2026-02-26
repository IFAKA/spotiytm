# Spotify → YouTube Music

Convert any public Spotify playlist to YouTube Music — no Spotify account needed.

![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-green) ![Platform](https://img.shields.io/badge/platform-Mac%20%7C%20Windows-lightgrey)

## Features

- **No Spotify account required** — scrapes the public embed page
- **Live progress** — real-time track-by-track updates via SSE
- **Checkpoint resume** — picks up where it left off if interrupted
- **Two-stage search** — songs filter first, then unfiltered fallback for better match rates
- **Parallel search** — 5 concurrent searches for speed

## Quick Start

### Mac
```bash
# Double-click Start.command
# or run in terminal:
./run.sh
```

### Windows
Double-click `Start.bat`

Both launchers auto-create a virtual environment and install dependencies.

Opens at **http://localhost:3000**

## First Run — YouTube Music Auth

On first launch you'll be prompted to connect your YouTube Music account (OAuth). A browser window opens automatically — sign in once and credentials are saved to `oauth.json`.

## How It Works

1. Paste a public Spotify playlist URL
2. Preview the tracks
3. Click **Convert** — tracks are searched on YouTube Music in parallel
4. A new YouTube Music playlist is created with all found tracks

## Requirements

- Python 3.9+
- A YouTube Music account

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + uvicorn |
| YT Music | ytmusicapi (OAuth) |
| Spotify | Embed page scraping (`__NEXT_DATA__`) |
| Frontend | Tailwind CSS + Alpine.js |
| Streaming | Server-Sent Events (SSE) |

## File Structure

```
app.py                  Entry point + all route handlers
backend/
  spotify.py            Embed scraper → track list
  ytmusic.py            YT Music search + playlist creation
  convert.py            SSE orchestrator, concurrency, checkpoint resume
  auth.py               OAuth helpers
templates/index.html    Single-page UI
static/app.js           Alpine.js component (SSE client + state machine)
checkpoints/            Runtime: per-conversion checkpoint files (git-ignored)
```

## Notes

- Playlist conversion is limited to tracks found on YouTube Music; missing tracks are listed at the end
- `oauth.json` and `headers_auth.json` contain your credentials — never commit them
- If Spotify changes their embed page structure, update the `__NEXT_DATA__` path in `backend/spotify.py`
