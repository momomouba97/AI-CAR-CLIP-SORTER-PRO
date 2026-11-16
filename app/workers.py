"""Background workers. Network / yt-dlp work never runs on the UI thread."""
from PySide6.QtCore import QThread, Signal

from .channel_parser import ChannelParser, ImportCancelled, ImportFailed, InvalidChannelURL


class ImportWorker(QThread):
    progress = Signal(int)
    imported = Signal(str, str, int, int)   # channel_id, title, saved, skipped
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, url, db, parser=None, parent=None):
        super().__init__(parent)
        self._url, self._db = url, db
        self._parser = parser or ChannelParser()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = self._parser.fetch_channel(self._url, self.progress.emit, lambda: self._cancel)
            self._db.upsert_channel(res.channel_id, res.title, res.url)
            saved = self._db.upsert_videos(res.channel_id, res.videos)
            self._db.log_activity("import", f"Imported {res.title}: {saved} videos")
            self.imported.emit(res.channel_id, res.title, saved, res.skipped)
        except ImportCancelled:
            self.cancelled.emit()
        except (ImportFailed, InvalidChannelURL) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")
