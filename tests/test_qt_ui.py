import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPointF, QRect, Qt, Signal, QObject
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from app.channel_parser import ChannelParser
from app.database import Database
from app.thumbnail_manager import ThumbnailManager, is_allowed_thumbnail_url
from app.video_manager import VideoManager
from app.workers import ImportWorker
from ui.video_list import ROW_HEIGHT, VideoListModel, VideoRowDelegate
from tests.test_video_manager import make_videos


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "q.db")
    d.upsert_channel("UC1", "Chan", "https://www.youtube.com/@chan/videos")
    d.upsert_videos("UC1", make_videos())
    yield d
    d.close()


class FakeThumbs(QObject):
    thumbnailReady = Signal(str)
    def get(self, vid, url):
        pm = QPixmap(160, 90); pm.fill(QColor("#3b4a6b")); return pm
    def shutdown(self): pass


def test_model_checkbox_and_flags(app, db):
    vm = VideoManager(db, 50)
    m = VideoListModel(vm); m.reload()
    assert m.rowCount() == 50
    i = m.index(0)
    assert m.data(i, Qt.CheckStateRole) == Qt.Unchecked
    assert m.setData(i, Qt.Checked, Qt.CheckStateRole)
    assert m.data(i, Qt.CheckStateRole) == Qt.Checked
    assert db.get_video(m.data(i, Qt.UserRole + 1)["video_id"])["selected"] == 1
    vm.set_filter("unavailable"); m.reload()
    assert not (m.flags(m.index(0)) & Qt.ItemIsUserCheckable)
    assert not m.setData(m.index(0), Qt.Checked, Qt.CheckStateRole)


def test_delegate_checkbox_hit_test_is_independent_of_thumbnail(app, db):
    vm = VideoManager(db, 50)
    m = VideoListModel(vm); m.reload()
    d = VideoRowDelegate(FakeThumbs())
    opt = QStyleOptionViewItem(); opt.rect = QRect(0, 0, 900, ROW_HEIGHT)
    def click(x, y):
        ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(x, y), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        return d.editorEvent(ev, m, opt, m.index(0))
    assert click(150, 40) is False                      # thumbnail area: no toggle
    assert m.data(m.index(0), Qt.CheckStateRole) == Qt.Unchecked
    cb = d.checkbox_rect(opt.rect).center()
    assert click(cb.x(), cb.y()) is True                # checkbox: toggles
    assert m.data(m.index(0), Qt.CheckStateRole) == Qt.Checked
    assert click(cb.x(), cb.y()) is True                # and back
    assert m.data(m.index(0), Qt.CheckStateRole) == Qt.Unchecked


def test_delegate_paints_all_states(app, db):
    vm = VideoManager(db, 50)
    for flt in ("all", "unavailable"):
        vm.set_filter(flt)
        m = VideoListModel(vm); m.reload()
        d = VideoRowDelegate(FakeThumbs())
        img = QImage(900, ROW_HEIGHT * 3, QImage.Format_ARGB32); img.fill(QColor("#191C23"))
        p = QPainter(img)
        for r in range(3):
            opt = QStyleOptionViewItem(); opt.rect = QRect(0, r * ROW_HEIGHT, 900, ROW_HEIGHT)
            d.paint(p, opt, m.index(r))
        p.end()
        assert not img.isNull()


def test_import_worker_with_fake_parser(app, db):
    class FakeYDL:
        def __init__(s, o): pass
        def __enter__(s): return s
        def __exit__(s, *a): return False
        def extract_info(s, url, download=False, process=True):
            return {"channel_id": "UC9", "channel": "New Chan",
                    "entries": [{"id": f"w{i:010d}", "title": f"W{i}", "duration": 10} for i in range(300)]}
    w = ImportWorker("@newchan", db, parser=ChannelParser(lambda o: FakeYDL(o)))
    got = {}
    w.imported.connect(lambda cid, t, n, s: got.update(cid=cid, t=t, n=n))
    w.failed.connect(lambda m: got.update(err=m))
    w.start(); assert w.wait(10000)
    app.processEvents()
    assert got == {"cid": "UC9", "t": "New Chan", "n": 300}
    assert db.count_videos("UC9") == 300
    assert db.recent_activity(1)[0]["kind"] == "import"


def test_import_worker_reports_invalid_url(app, db):
    w = ImportWorker("https://evil.com/@x", db)
    errs = []
    w.failed.connect(errs.append)
    w.start(); assert w.wait(5000); app.processEvents()
    assert errs and "youtube.com" in errs[0]


def test_thumbnail_url_allowlist_and_cache(app, tmp_path):
    assert is_allowed_thumbnail_url("https://i.ytimg.com/vi/x/mqdefault.jpg")
    assert not is_allowed_thumbnail_url("http://i.ytimg.com/vi/x/a.jpg")
    assert not is_allowed_thumbnail_url("https://evil.com/a.jpg")
    assert not is_allowed_thumbnail_url("https://ytimg.com.evil.com/a.jpg")
    tm = ThumbnailManager(tmp_path / "c", max_mb=50)
    assert tm.get("v", "https://evil.com/a.jpg") is None       # never fetched
    pm = QPixmap(10, 10); pm.fill(QColor("red"))
    pm.save(str(tm._path("v1", "https://i.ytimg.com/a.jpg")), "PNG")
    assert tm.get("v1", "https://i.ytimg.com/a.jpg") is not None   # served from disk cache
    assert tm.disk_usage() > 0
    tm.clear(); assert tm.disk_usage() == 0
    tm.shutdown()


def test_main_window_builds_and_close_while_importing(app, db, tmp_path):
    from app.main_window import MainWindow
    from app.settings_manager import SettingsManager
    win = MainWindow(db, SettingsManager(tmp_path / "s.json"), FakeThumbs())
    win.show(); app.processEvents()
    assert win.model.rowCount() == 50 and "Page 1 of 3" in win.page_label.text()
    win.next_btn.click(); app.processEvents()
    assert "Page 2 of 3" in win.page_label.text()
    win.search.setText("Video 05"); app.processEvents()
    assert "10 videos" in win.page_label.text()
    img = win.grab()
    assert not img.isNull()
    win.close()
