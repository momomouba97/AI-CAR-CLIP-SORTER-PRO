"""Lazy thumbnail loading with an in-memory LRU and an on-disk cache (never blocks the UI)."""
import hashlib
import os
import ssl
import urllib.request
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QPixmap

ALLOWED_SUFFIXES = (".ytimg.com", ".ggpht.com", ".googleusercontent.com", ".youtube.com")


def is_allowed_thumbnail_url(url: str) -> bool:
    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == s[1:] or host.endswith(s) for s in ALLOWED_SUFFIXES)


def _ssl_context():
    """python.org builds have no system CA bundle; use certifi's."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class _Signals(QObject):
    done = Signal(str, bool)  # video_id, ok


class _Fetch(QRunnable):
    def __init__(self, video_id, url, dest, signals):
        super().__init__()
        self.video_id, self.url, self.dest, self.signals = video_id, url, dest, signals

    def run(self):
        ok = False
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:
                data = r.read(5 * 1024 * 1024)
            tmp = self.dest.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, self.dest)
            ok = True
        except Exception:
            pass
        self.signals.done.emit(self.video_id, ok)


class ThumbnailManager(QObject):
    thumbnailReady = Signal(str)  # video_id

    def __init__(self, cache_dir, max_mb=500, mem_items=400, parent=None):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_mb) * 1024 * 1024
        self._mem = OrderedDict()
        self._mem_items = mem_items
        self._pending = set()
        self._failed = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._fetched = 0

    def _path(self, video_id, url):
        return self.cache_dir / (hashlib.sha1(f"{video_id}|{url}".encode()).hexdigest() + ".img")

    def get(self, video_id, url):
        """Return a QPixmap if available now; otherwise queue a download and return None."""
        if video_id in self._mem:
            self._mem.move_to_end(video_id)
            return self._mem[video_id]
        if not url or video_id in self._failed or not is_allowed_thumbnail_url(url):
            return None
        path = self._path(video_id, url)
        if path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                self._remember(video_id, pm)
                return pm
            path.unlink(missing_ok=True)
        if video_id not in self._pending:
            self._pending.add(video_id)
            self._pool.start(_Fetch(video_id, url, path, self._signals))
        return None

    def _remember(self, video_id, pm):
        self._mem[video_id] = pm
        while len(self._mem) > self._mem_items:
            self._mem.popitem(last=False)

    def _on_done(self, video_id, ok):
        self._pending.discard(video_id)
        if ok:
            self._fetched += 1
            if self._fetched % 50 == 0:
                self.prune()
            self.thumbnailReady.emit(video_id)
        else:
            self._failed.add(video_id)

    def disk_usage(self):
        return sum(f.stat().st_size for f in self.cache_dir.glob("*.img"))

    def prune(self):
        files = sorted(self.cache_dir.glob("*.img"), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        while files and total > self.max_bytes:
            f = files.pop(0)
            total -= f.stat().st_size
            f.unlink(missing_ok=True)

    def clear(self):
        self._mem.clear()
        self._failed.clear()
        for f in self.cache_dir.glob("*.img"):
            f.unlink(missing_ok=True)

    def shutdown(self):
        self._pool.clear()
        self._pool.waitForDone(3000)
