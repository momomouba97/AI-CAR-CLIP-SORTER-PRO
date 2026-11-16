# YouTube Downloader Studio

Desktop app (Python + PySide6 + yt-dlp + FFmpeg) for importing a YouTube channel's public videos,
selecting the ones you want, and downloading them in bulk. Target: **macOS 11.7 (Big Sur), Intel x86_64**.

> Only download content you own or have the right to download. The app does not bypass DRM or access controls.

## Status: Phase 1 of 4

| Phase | Scope | State |
|---|---|---|
| 1 | SQLite storage, settings, channel import (yt-dlp), paginated vertical library with persistent selection, thumbnail cache, preview window | **Done – unit-tested headless on Linux** |
| 2 | Parallel download manager (≤10), retries, FFmpeg merge, ZIP export | Not started |
| 3 | Full UI: sidebar, dashboard, downloads/completed/failed/export/settings pages, light/dark, notifications | Not started |
| 4 | PyInstaller spec, DMG scripts, GitHub Actions, final README | Not started |

### What is and is not verified
- Verified: core logic and Qt model/delegate/worker code (38 tests, offscreen Qt, PySide6 6.6.3.1 on Linux / Python 3.12).
- Verified: PySide6 6.5.3 x86_64 Qt binaries declare minimum macOS **11.0** (read from the Mach-O headers of QtCore and libqcocoa).
- **Not verified:** real YouTube import (no network access to YouTube in the build sandbox), anything on macOS,
  PySide6 6.5.3 itself (needs Python <= 3.11, the sandbox had 3.12), DMG build.
- Channel listings from yt-dlp's flat extraction often lack upload dates, so the date column may show "Date unknown"
  until a later phase enriches them.

## Run (Mac Intel, Python 3.11)
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Test
```bash
pytest -q
```

## Data location
`~/Library/Application Support/YouTube Downloader Studio/` – `Database/library.db` (with rolling backups),
`settings.json`, `Cache/Thumbnails/`, `Logs/app.log`, `Downloads/`. Set `YTDS_DATA_DIR` to override.

## Phase 1 behaviour
- Accepts `@handle`, `/channel/UC…`, `/c/…`, `/user/…` links (any tab is normalised to `/videos`); other hosts are rejected.
- No artificial limit on imported videos; private/deleted/upcoming/members-only items are stored with their own availability and cannot be selected.
- 50 videos per page; selection is stored in SQLite, survives paging and restarts.
- Shortcuts: Ctrl/⌘+I focus import, Ctrl/⌘+F search, Ctrl/⌘+D deselect all.
