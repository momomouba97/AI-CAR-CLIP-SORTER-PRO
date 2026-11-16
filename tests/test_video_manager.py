import pytest
from app.database import Database
from app.settings_manager import SettingsManager
from app.video_manager import VideoManager, format_duration


def make_videos(n=120):
    vids = []
    for i in range(n):
        vids.append({"video_id": f"vid{i:08d}", "title": f"Video {i:03d}" + (" 100%_off" if i == 7 else ""),
                     "thumbnail": "", "duration": 60 + i, "upload_date": f"2024-01-{(i % 28) + 1:02d}",
                     "url": f"https://www.youtube.com/watch?v=vid{i:08d}",
                     "availability": "private" if i % 10 == 9 else "public"})
    return vids


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    d.upsert_channel("UC1", "Chan", "https://www.youtube.com/@chan/videos")
    d.upsert_videos("UC1", make_videos())
    yield d
    d.close()


def test_pagination_50(db):
    vm = VideoManager(db, 50)
    assert vm.total() == 120 and vm.total_pages() == 3
    assert len(vm.rows()) == 50
    vm.next_page(); assert len(vm.rows()) == 50
    vm.next_page(); assert len(vm.rows()) == 20
    assert vm.next_page() == 2  # clamped
    vm.goto(0); assert vm.prev_page() == 0


def test_selection_persists_across_pages_and_restart(db, tmp_path):
    vm = VideoManager(db, 50)
    vm.select_current_page(True)
    vm.next_page()
    first = vm.rows()[0]["video_id"]
    assert vm.toggle(first, True)
    n = vm.summary()["selected"]
    assert n > 0
    vm.goto(0)
    assert vm.summary()["on_page"] == sum(1 for r in vm.rows() if r["video_id"] and r["selected"])
    db2 = Database(tmp_path / "t.db")           # second connection = fresh process view
    assert VideoManager(db2, 50).summary()["selected"] == n
    db2.close()


def test_select_entire_channel_skips_unavailable(db):
    vm = VideoManager(db, 50)
    vm.set_channel("UC1")
    assert vm.select_entire_channel() == 108          # 120 minus 12 private
    assert vm.summary()["selected"] == 108
    assert vm.toggle("vid00000009", True) is False    # private video cannot be selected
    vm.deselect_all()
    assert vm.summary()["selected"] == 0


def test_upsert_preserves_selection_and_status(db):
    db.set_selected(["vid00000001"], True)
    db.set_download_status("vid00000001", "completed", "/x.mp4")
    db.upsert_videos("UC1", [dict(make_videos(2)[1], title="Renamed", upload_date="")])
    r = db.get_video("vid00000001")
    assert r["selected"] == 1 and r["download_status"] == "completed"
    assert r["title"] == "Renamed" and r["upload_date"] == "2024-01-02"  # empty date does not erase


def test_search_filter_sort(db):
    vm = VideoManager(db, 50)
    vm.set_search("100%_off"); assert vm.total() == 1      # % and _ are literal
    vm.set_search("Video 05"); assert vm.total() == 10
    vm.set_search("vid00000003"); assert vm.total() == 1   # search by ID
    vm.set_search("")
    vm.set_filter("unavailable"); assert vm.total() == 12
    vm.set_filter("available"); assert vm.total() == 108
    db.set_download_status("vid00000000", "completed"); db.set_download_status("vid00000001", "failed")
    vm.set_filter("downloaded"); assert vm.total() == 1
    vm.set_filter("failed"); assert vm.total() == 1
    vm.set_filter("not_downloaded"); assert vm.total() == 118
    vm.set_filter("all")
    vm.set_sort("duration", descending=True); assert vm.rows()[0]["duration"] == 179
    vm.set_sort("title", descending=False); assert vm.rows()[0]["title"].startswith("Video 000")


def test_select_matching_and_bad_inputs(db):
    vm = VideoManager(db, 50)
    vm.set_search("Video 01")
    assert vm.select_matching() == 9   # Video 010..019, minus private vid...019
    with pytest.raises(ValueError):
        db.query_videos(sort="title; DROP TABLE videos")
    with pytest.raises(ValueError):
        db.count_videos(status="x' OR 1=1")


def test_backup_and_activity(db, tmp_path):
    db.log_activity("import", "Imported Chan")
    assert db.recent_activity(1)[0]["message"] == "Imported Chan"
    for _ in range(7):
        p = db.backup(tmp_path / "b", keep=5)
    assert p.exists() and len(list((tmp_path / "b").glob("library-*.db"))) <= 5


def test_format_duration():
    assert format_duration(59) == "0:59" and format_duration(3661) == "1:01:01"


def test_settings_validation_and_persistence(tmp_path):
    p = tmp_path / "s.json"
    s = SettingsManager(p)
    s.set("parallel_downloads", 99); assert s.get("parallel_downloads") == 10
    s.set("max_quality", 4320); assert s.get("max_quality") == 1080
    s.set("theme", "light")
    assert SettingsManager(p).get("theme") == "light"
    p.write_text("{not json")
    assert SettingsManager(p).get("page_size") == 50
    with pytest.raises(KeyError):
        s.set("nope", 1)
