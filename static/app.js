/**
 * Alpine.js component: spotifyConverter
 *
 * Queue-based conversion: multiple playlists process one by one.
 * Auth auto-runs on page load.
 */

function spotifyConverter() {
  return {
    // --- Auth ---
    connected: false,
    checkingAuth: true,
    authLoading: false,
    authError: '',
    authStatus: '',
    authNeedsSignIn: false,
    _authPollTimer: null,

    // --- Input ---
    spotifyUrl: '',
    inputError: '',
    clipboardSuggestions: [],

    // --- Queue ---
    // Each item: { id, url, status, name, total, found, missing, playlistId, tracks, logs, showDebug, error }
    // status: 'pending' | 'active' | 'done' | 'error'
    queue: [],
    _queueRunning: false,
    _nextId: 1,
    _activeSse: null,

    // ── Lifecycle ─────────────────────────────────────────────────────────

    async init() {
      await this.checkAuth();
      if (this.connected) {
        this.tryPasteFromClipboard();
      } else {
        await this.startAuth();
      }
    },

    // ── Auth ──────────────────────────────────────────────────────────────

    async checkAuth() {
      this.checkingAuth = true;
      try {
        const res = await fetch('/api/auth/status');
        const data = await res.json();
        this.connected = data.connected;
      } catch (_) {
        this.connected = false;
      } finally {
        this.checkingAuth = false;
      }
    },

    async startAuth() {
      this.authError = '';
      this.authStatus = '';
      this.authLoading = true;
      try {
        const res = await fetch('/api/auth/start', { method: 'POST' });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || 'Failed to start auth.');
        }
      } catch (e) {
        this.authError = e.message;
        this.authLoading = false;
        return;
      }
      this._authPollTimer = setInterval(async () => {
        try {
          const res = await fetch('/api/auth/status');
          const data = await res.json();
          if (data.status) this.authStatus = data.status;
          if (data.playwrightActive) this.authNeedsSignIn = true;
          if (data.connected) {
            this._stopAuthPoll();
            this.connected = true;
            this.authLoading = false;
            this.authNeedsSignIn = false;
            this.tryPasteFromClipboard();
          } else if (data.error) {
            this._stopAuthPoll();
            this.authError = data.error;
            this.authLoading = false;
          }
        } catch (_) {}
      }, 1500);

      setTimeout(() => {
        if (this._authPollTimer) {
          this._stopAuthPoll();
          this.authError = 'Timed out. Please try again.';
          this.authLoading = false;
        }
      }, 5 * 60 * 1000);
    },

    async cancelAuth() {
      this._stopAuthPoll();
      this.authLoading = false;
      this.authError = '';
      this.authNeedsSignIn = false;
      try { await fetch('/api/auth/cancel', { method: 'POST' }); } catch (_) {}
    },

    _stopAuthPoll() {
      if (this._authPollTimer) {
        clearInterval(this._authPollTimer);
        this._authPollTimer = null;
      }
    },

    // ── Clipboard ─────────────────────────────────────────────────────────

    async tryPasteFromClipboard() {
      try {
        const text = await navigator.clipboard.readText();
        const matches = [...text.matchAll(/https?:\/\/open\.spotify\.com\/playlist\/[A-Za-z0-9]+/g)]
          .map(m => m[0]);
        if (matches.length === 1) {
          this.spotifyUrl = matches[0];
        } else if (matches.length > 1) {
          this.clipboardSuggestions = matches;
        }
      } catch (_) {}
    },

    addAllSuggestions() {
      this.clipboardSuggestions.forEach(url => this._enqueue(url));
      this.clipboardSuggestions = [];
    },

    // ── Input / Queue management ──────────────────────────────────────────

    _cleanUrl(raw) {
      return (raw || '').trim().split(/[\s,]+/)[0].replace(/[?#].*$/, '');
    },

    submit() {
      this.inputError = '';
      const url = this._cleanUrl(this.spotifyUrl);
      if (!url) {
        this.inputError = 'Please enter a Spotify playlist URL.';
        return;
      }
      if (!url.includes('spotify.com/playlist/')) {
        this.inputError = 'That doesn\'t look like a Spotify playlist URL.';
        return;
      }
      if (this._enqueue(url)) {
        this.spotifyUrl = '';
        this.clipboardSuggestions = [];
      } else {
        this.inputError = 'That playlist is already in the queue.';
      }
    },

    _enqueue(url) {
      url = this._cleanUrl(url);
      if (this.queue.some(i => i.url === url)) return false;
      this.queue.push({
        id: this._nextId++,
        url,
        status: 'pending',
        name: '',
        total: 0,
        found: 0,
        missing: 0,
        playlistId: null,
        tracks: [],
        logs: [],
        showDebug: false,
        error: null,
      });
      this._maybeStart();
      return true;
    },

    removeItem(id) {
      this.queue = this.queue.filter(i => i.id !== id || i.status === 'active');
    },

    retryItem(id) {
      const item = this.queue.find(i => i.id === id);
      if (!item) return;
      item.status = 'pending';
      item.found = 0;
      item.missing = 0;
      item.tracks = [];
      item.logs = [];
      item.showDebug = false;
      item.error = null;
      this._maybeStart();
    },

    // ── Queue processor ───────────────────────────────────────────────────

    _maybeStart() {
      if (!this._queueRunning) this._processNext();
    },

    _processNext() {
      const item = this.queue.find(i => i.status === 'pending');
      if (!item) { this._queueRunning = false; return; }
      this._queueRunning = true;
      item.status = 'active';
      this._runItem(item);
    },

    _runItem(item) {
      const sse = new EventSource(`/api/convert?url=${encodeURIComponent(item.url)}`);
      this._activeSse = sse;

      sse.onmessage = (e) => {
        let evt;
        try { evt = JSON.parse(e.data); } catch (_) { return; }

        const ts = new Date().toLocaleTimeString('en-US', { hour12: false });

        switch (evt.type) {
          case 'fetching':
            item.logs.push({ time: ts, message: 'Fetching Spotify playlist…' });
            break;

          case 'fetched':
            item.name = evt.name || item.url;
            item.total = evt.total || 0;
            break;

          case 'log':
            item.logs.push({ time: ts, message: evt.message });
            break;

          case 'track':
            if (evt.status === 'found') item.found++;
            else item.missing++;
            item.tracks.push({ name: evt.name, artists: evt.artists, status: evt.status });
            this.$nextTick(() => {
              const el = document.querySelector(`[data-tracks="${item.id}"]`);
              if (el) el.scrollTop = el.scrollHeight;
            });
            break;

          case 'done':
            item.logs.push({ time: ts, message: `Done: ${evt.found} added, ${evt.missing} not found on YouTube Music` });
            item.status = 'done';
            item.playlistId = evt.playlistId || '';
            item.found = evt.found ?? item.found;
            item.missing = evt.missing ?? item.missing;
            sse.close();
            this._processNext();
            break;

          case 'error':
            item.logs.push({ time: ts, message: `Error: ${evt.message}` });
            item.status = 'error';
            item.error = evt.message || 'Unknown error.';
            item.showDebug = true;  // auto-expand debug on error
            sse.close();
            this._processNext();
            break;
        }
      };

      sse.onerror = () => {
        if (item.status === 'active') {
          const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
          item.logs.push({ time: ts, message: 'SSE connection lost unexpectedly' });
          item.status = 'error';
          item.error = 'Connection lost.';
          item.showDebug = true;
          this._processNext();
        }
        sse.close();
      };
    },

    // ── Debug helpers ─────────────────────────────────────────────────────

    copyDebugLog(item) {
      const lines = [
        'Spotify → YouTube Music Converter — Debug Report',
        '',
        `Playlist: ${item.url}`,
        `Name:     ${item.name || '(not fetched yet)'}`,
        `Status:   ${item.status}`,
      ];
      if (item.total) {
        lines.push(`Tracks:   ${item.found} found, ${item.missing} missing / ${item.total} total`);
      }
      if (item.playlistId) {
        lines.push(`YT Playlist: https://music.youtube.com/playlist?list=${item.playlistId}`);
      }
      if (item.error) {
        lines.push('', 'Error:', item.error);
      }
      lines.push('', 'Event Log:');
      item.logs.forEach(e => lines.push(`[${e.time}] ${e.message}`));

      navigator.clipboard.writeText(lines.join('\n')).catch(() => {});
    },

    // ── Helpers ───────────────────────────────────────────────────────────

    get queueHasItems() { return this.queue.length > 0; },
    get pendingCount()  { return this.queue.filter(i => i.status === 'pending').length; },
    get activeItem()    { return this.queue.find(i => i.status === 'active') || null; },
    get progress()      {
      const a = this.activeItem;
      if (!a || !a.total) return 0;
      return Math.round(((a.found + a.missing) / a.total) * 100);
    },

    shortUrl(url) {
      const m = url.match(/playlist\/([A-Za-z0-9]+)/);
      return m ? `spotify:playlist:${m[1].slice(0, 8)}…` : url;
    },
  };
}
