# Spotify → YouTube Music Converter

Local web app that converts public Spotify playlists to YouTube Music — no Spotify account needed.

## Stack
- **Backend**: FastAPI + uvicorn (Python)
- **Auth**: ytmusicapi OAuth (`oauth.json` auto-created on first run)
- **Spotify**: Scrapes embed page `__NEXT_DATA__` JSON (no Spotify API key needed)
- **Frontend**: Single-page app — Tailwind CDN + Alpine.js, SSE for live progress
- **Launchers**: `Start.command` (Mac), `Start.bat` (Windows) — handle venv + deps automatically

## Run
```
./run.sh           # Mac/Linux
Start.command      # Mac double-click
Start.bat          # Windows double-click
```
Opens browser at `http://localhost:3000`.

## File Structure
```
app.py                  FastAPI entry point + all route handlers
backend/
  spotify.py            Embed scraper → track list
  ytmusic.py            YT Music search + playlist creation
  convert.py            SSE orchestrator, asyncio concurrency, checkpoint resume
  auth.py               OAuth helpers
templates/index.html    Single-page UI
static/app.js           Alpine.js component (SSE client + state machine)
checkpoints/            Runtime: checkpoint_{id}.json for resume (git-ignored)
```

## Key Architecture
- **Spotify scrape**: `props.pageProps.state.data.entity` inside `<script id="__NEXT_DATA__">`
- **YT search**: two-stage — songs filter first, then unfiltered fallback
- **Concurrency**: `asyncio.Semaphore(5)` for parallel track searches
- **SSE stream**: `GET /api/convert?url=` sends `fetching | fetched | track | done | error` events
- **OAuth**: runs in background thread so server stays responsive
- **Checkpoint**: saves `videoId` after each track; file deleted on success; resume on retry

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | index.html |
| GET | `/api/auth/status` | `{ connected: bool }` |
| POST | `/api/auth/start` | starts OAuth in background thread |
| GET | `/api/spotify?url=` | preview: `{ name, total, tracks[] }` |
| GET | `/api/convert?url=` | SSE stream |

## SSE Event Schema
```
fetching          – started scraping Spotify
fetched           – { name, total }
track             – { i, total, name, artists, status, videoId? }
done              – { playlistId, found, missing, missingTracks[] }
error             – { message }
```

## Dev Notes
- Port is hardcoded to **3000**
- Add tracks in batches of 50 (YT Music API limit)
- `create_playlist` returns `playlistId` as a plain string
- Playwright is used for cookie-based auth fallback
- `headers_auth.json` and `oauth.json` are user credentials — never commit
- If Spotify changes embed HTML, update the `__NEXT_DATA__` path in `backend/spotify.py`
