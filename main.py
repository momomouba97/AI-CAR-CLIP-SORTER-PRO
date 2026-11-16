"""YouTube Downloader Studio – entry point."""
import logging
import sys

from PySide6.QtWidgets import QApplication

from app.database import Database
from app.main_window import MainWindow
from app.settings_manager import APP_NAME, SettingsManager, data_dir, ensure_dirs
from app.thumbnail_manager import ThumbnailManager


def main() -> int:
    base = data_dir()
    dirs = ensure_dirs(base)
    logging.basicConfig(filename=str(dirs["logs"] / "app.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    settings = SettingsManager(base / "settings.json")
    if not settings.get("download_dir"):
        settings.set("download_dir", str(dirs["downloads"]))
    db = Database(dirs["database"] / "library.db")
    try:
        db.backup(dirs["backups"])
    except Exception:
        logging.exception("backup failed")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    thumbs = ThumbnailManager(dirs["thumbnails"], settings.get("thumbnail_cache_mb"))
    win = MainWindow(db, settings, thumbs)
    win.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
