"""`--selftest`: verifies that a frozen build really contains everything it needs."""
import os
import platform
import subprocess
import sys
import tempfile


def run(require_ffmpeg=False) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tmp = tempfile.mkdtemp(prefix="ytds-selftest-")
    os.environ["YTDS_DATA_DIR"] = tmp
    failures = []

    def step(name, fn):
        try:
            print(f"[ok]   {name}: {fn()}")
        except Exception as exc:
            print(f"[FAIL] {name}: {exc!r}")
            failures.append(name)

    def versions():
        import PySide6
        import sqlite3
        import yt_dlp
        return (f"python {platform.python_version()} {platform.machine()} | PySide6 {PySide6.__version__} | "
                f"yt-dlp {yt_dlp.version.__version__} | sqlite {sqlite3.sqlite_version}")

    def extractors():
        import yt_dlp.extractor.youtube  # noqa: F401  (must be inside the bundle)
        import certifi, os as _os
        assert _os.path.isfile(certifi.where()), "certifi CA bundle missing"
        return "youtube extractor + CA bundle present"

    def tool(name):
        from app.resources import tool_path
        p = tool_path(name)
        if not p:
            if require_ffmpeg:
                raise RuntimeError(f"{name} not bundled")
            return f"{name} not bundled (allowed)"
        out = subprocess.run([p, "-version"], capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise RuntimeError(f"{name} failed to run: {out.stderr[:200]}")
        return out.stdout.splitlines()[0]

    def gui():
        from PySide6.QtWidgets import QApplication
        from app.database import Database
        from app.main_window import MainWindow
        from app.settings_manager import SettingsManager
        from app.thumbnail_manager import ThumbnailManager
        app = QApplication.instance() or QApplication([])
        db = Database(os.path.join(tmp, "selftest.db"))
        win = MainWindow(db, SettingsManager(os.path.join(tmp, "s.json")),
                         ThumbnailManager(os.path.join(tmp, "thumbs")))
        win.show()
        app.processEvents()
        win.close()
        db.close()
        return "main window created and closed"

    step("versions", versions)
    step("yt-dlp bundle", extractors)
    step("ffmpeg", lambda: tool("ffmpeg"))
    step("ffprobe", lambda: tool("ffprobe"))
    step("gui (offscreen)", gui)
    print("SELFTEST FAILED: " + ", ".join(failures) if failures else "SELFTEST OK")
    return 1 if failures else 0
