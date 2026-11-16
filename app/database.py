"""SQLite storage: channels, videos (with persistent selection), activity log."""
import sqlite3
import threading
import time
from pathlib import Path

AVAILABLE = ("public", "unlisted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    imported_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    thumbnail TEXT NOT NULL DEFAULT '',
    duration INTEGER NOT NULL DEFAULT 0,
    upload_date TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    availability TEXT NOT NULL DEFAULT 'public',
    selected INTEGER NOT NULL DEFAULT 0,
    download_status TEXT NOT NULL DEFAULT 'none',
    file_path TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_selected ON videos(selected);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
"""

_AV = ",".join(f"'{a}'" for a in AVAILABLE)
SORTS = {"date": "upload_date", "title": "title COLLATE NOCASE", "duration": "duration"}
FILTERS = {
    "all": "1=1",
    "downloaded": "download_status = 'completed'",
    "not_downloaded": "download_status = 'none'",
    "failed": "download_status = 'failed'",
    "available": f"availability IN ({_AV})",
    "unavailable": f"availability NOT IN ({_AV})",
}


def _like(text):
    esc = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


class Database:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    # ---- helpers -------------------------------------------------------
    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _one(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    @staticmethod
    def _where(channel_id=None, search="", status="all"):
        if status not in FILTERS:
            raise ValueError(f"unknown filter: {status}")
        clauses, params = [FILTERS[status]], []
        if channel_id:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if search:
            clauses.append("(title LIKE ? ESCAPE '\\' OR video_id LIKE ? ESCAPE '\\')")
            params += [_like(search), _like(search)]
        return " AND ".join(clauses), params

    # ---- channels ------------------------------------------------------
    def upsert_channel(self, channel_id, title, url):
        self._exec(
            "INSERT INTO channels(channel_id,title,url,imported_at) VALUES(?,?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title,"
            "url=excluded.url,imported_at=excluded.imported_at",
            (channel_id, title, url, time.time()))

    def list_channels(self):
        return self._all(
            "SELECT c.*, (SELECT COUNT(*) FROM videos v WHERE v.channel_id=c.channel_id) AS video_count "
            "FROM channels c ORDER BY imported_at DESC")

    def delete_channel(self, channel_id):
        self._exec("DELETE FROM channels WHERE channel_id=?", (channel_id,))

    # ---- videos --------------------------------------------------------
    def upsert_videos(self, channel_id, videos):
        """Insert/update. Existing selection and download state are preserved."""
        now = time.time()
        rows = [(v["video_id"], channel_id, v["title"], v.get("thumbnail", ""),
                 int(v.get("duration") or 0), v.get("upload_date", ""), v["url"],
                 v.get("availability", "public"), now) for v in videos]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO videos(video_id,channel_id,title,thumbnail,duration,upload_date,url,availability,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET "
                "channel_id=excluded.channel_id, title=excluded.title, thumbnail=excluded.thumbnail,"
                "duration=excluded.duration, url=excluded.url, availability=excluded.availability,"
                "updated_at=excluded.updated_at,"
                "upload_date=CASE WHEN excluded.upload_date!='' THEN excluded.upload_date ELSE videos.upload_date END",
                rows)
            self._conn.commit()
        return len(rows)

    def query_videos(self, channel_id=None, search="", status="all", sort="date",
                     descending=True, limit=50, offset=0):
        if sort not in SORTS:
            raise ValueError(f"unknown sort: {sort}")
        where, params = self._where(channel_id, search, status)
        order = f"{SORTS[sort]} {'DESC' if descending else 'ASC'}, video_id"
        return self._all(f"SELECT * FROM videos WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                         params + [int(limit), int(offset)])

    def count_videos(self, channel_id=None, search="", status="all"):
        where, params = self._where(channel_id, search, status)
        return self._one(f"SELECT COUNT(*) FROM videos WHERE {where}", params)[0]

    def get_video(self, video_id):
        return self._one("SELECT * FROM videos WHERE video_id=?", (video_id,))

    def set_download_status(self, video_id, status, file_path=""):
        self._exec("UPDATE videos SET download_status=?, file_path=? WHERE video_id=?",
                   (status, file_path, video_id))

    # ---- selection (persisted) ------------------------------------------
    def set_selected(self, video_ids, selected):
        """Unavailable videos can never be selected; deselecting always works."""
        ids = list(video_ids)
        extra = f" AND availability IN ({_AV})" if selected else ""
        with self._lock:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                self._conn.execute(
                    f"UPDATE videos SET selected=? WHERE video_id IN ({q}){extra}",
                    [1 if selected else 0] + chunk)
            self._conn.commit()

    def select_where(self, channel_id=None, search="", status="all", selected=True):
        where, params = self._where(channel_id, search, status)
        extra = f" AND availability IN ({_AV})" if selected else ""
        return self._exec(f"UPDATE videos SET selected=? WHERE {where}{extra}",
                          [1 if selected else 0] + params).rowcount

    def clear_selection(self, channel_id=None):
        if channel_id:
            self._exec("UPDATE videos SET selected=0 WHERE selected=1 AND channel_id=?", (channel_id,))
        else:
            self._exec("UPDATE videos SET selected=0 WHERE selected=1")

    def selected_videos(self, channel_id=None):
        if channel_id:
            return self._all("SELECT * FROM videos WHERE selected=1 AND channel_id=? ORDER BY upload_date DESC", (channel_id,))
        return self._all("SELECT * FROM videos WHERE selected=1 ORDER BY upload_date DESC")

    def selection_summary(self, channel_id=None):
        sql = "SELECT COUNT(*), COALESCE(SUM(duration),0) FROM videos WHERE selected=1"
        params = ()
        if channel_id:
            sql += " AND channel_id=?"
            params = (channel_id,)
        r = self._one(sql, params)
        return {"count": r[0], "duration": r[1]}

    # ---- stats / activity / backup ----------------------------------------
    def stats(self):
        r = self._one(
            "SELECT COUNT(*), SUM(selected), "
            "SUM(download_status='completed'), SUM(download_status='failed') FROM videos")
        return {"total": r[0] or 0, "selected": r[1] or 0,
                "completed": r[2] or 0, "failed": r[3] or 0}

    def log_activity(self, kind, message):
        self._exec("INSERT INTO activity(ts,kind,message) VALUES(?,?,?)", (time.time(), kind, message))

    def recent_activity(self, limit=20):
        return self._all("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))

    def backup(self, dest_dir, keep=5):
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"library-{time.strftime('%Y%m%d-%H%M%S')}.db"
        target = sqlite3.connect(str(dest))
        try:
            with self._lock:
                self._conn.backup(target)
        finally:
            target.close()
        for old in sorted(dest_dir.glob("library-*.db"))[:-keep]:
            old.unlink(missing_ok=True)
        return dest
