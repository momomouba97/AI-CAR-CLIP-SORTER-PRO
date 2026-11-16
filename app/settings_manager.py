"""Persistent user settings (JSON) and macOS data-directory layout."""
import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "YouTube Downloader Studio"


def data_dir() -> Path:
    """~/Library/Application Support/YouTube Downloader Studio on macOS."""
    override = os.environ.get("YTDS_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_NAME


def ensure_dirs(base: Path) -> dict:
    layout = {
        "downloads": base / "Downloads",
        "exports": base / "Exports" / "ZIP Files",
        "thumbnails": base / "Cache" / "Thumbnails",
        "logs": base / "Logs",
        "database": base / "Database",
        "backups": base / "Database" / "Backups",
    }
    for p in layout.values():
        p.mkdir(parents=True, exist_ok=True)
    return layout


DEFAULTS = {
    "max_quality": 1080,
    "format": "mp4",
    "parallel_downloads": 10,
    "retry_attempts": 3,
    "download_dir": "",
    "filename_template": "%(title)s [%(id)s].%(ext)s",
    "theme": "dark",
    "accent": "#E63946",
    "density": "comfortable",
    "page_size": 50,
    "thumbnail_cache_mb": 500,
    "sidebar_collapsed": False,
    "last_channel_id": "",
    "notify_completed": True,
    "notify_failed": True,
    "notify_zip": True,
}

_RANGES = {"parallel_downloads": (1, 10), "retry_attempts": (0, 10),
           "page_size": (10, 200), "thumbnail_cache_mb": (50, 5000)}
_CHOICES = {"max_quality": {360, 480, 720, 1080}, "format": {"mp4", "mkv"},
            "theme": {"dark", "light"}, "density": {"compact", "comfortable"}}


class SettingsManager:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if k in DEFAULTS:
                        self._data[k] = self._validate(k, v, self._data[k])
        except (OSError, ValueError):
            pass  # missing or corrupt file -> defaults

    @staticmethod
    def _validate(key, value, fallback):
        default = DEFAULTS[key]
        if isinstance(default, bool):
            return value if isinstance(value, bool) else fallback
        if isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                return fallback
            if key in _RANGES:
                lo, hi = _RANGES[key]
                return max(lo, min(hi, value))
            if key in _CHOICES and value not in _CHOICES[key]:
                return fallback
            return value
        if isinstance(default, str):
            if not isinstance(value, str):
                return fallback
            if key in _CHOICES and value not in _CHOICES[key]:
                return fallback
            return value
        return fallback

    def get(self, key):
        with self._lock:
            return self._data[key]

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        with self._lock:
            self._data[key] = self._validate(key, value, self._data[key])
            self._save_locked()

    def all(self):
        with self._lock:
            return dict(self._data)

    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
