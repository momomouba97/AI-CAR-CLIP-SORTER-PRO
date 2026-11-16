import pytest
from app.channel_parser import (ChannelParser, ImportCancelled, ImportFailed,
                                InvalidChannelURL, normalize_channel_url, parse_entry)


@pytest.mark.parametrize("text,expected", [
    ("@MrBeast", "https://www.youtube.com/@MrBeast/videos"),
    ("https://www.youtube.com/@MrBeast", "https://www.youtube.com/@MrBeast/videos"),
    ("youtube.com/@MrBeast/videos", "https://www.youtube.com/@MrBeast/videos"),
    ("https://m.youtube.com/@MrBeast/streams", "https://www.youtube.com/@MrBeast/videos"),
    ("https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA/videos",
     "https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA/videos"),
    ("UCX6OQ3DkcsbYNE6H8uQQuVA", "https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA/videos"),
    ("https://www.youtube.com/c/SomeName", "https://www.youtube.com/c/SomeName/videos"),
    ("https://www.youtube.com/user/SomeUser/", "https://www.youtube.com/user/SomeUser/videos"),
])
def test_valid_urls(text, expected):
    assert normalize_channel_url(text) == expected


@pytest.mark.parametrize("text", [
    "", "   ", "https://evil.com/@x", "https://youtube.com.evil.com/@x",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/",
    "javascript:alert(1)", "https://www.youtube.com/@a b;rm -rf", "ftp://youtube.com/@x",
])
def test_invalid_urls(text):
    with pytest.raises(InvalidChannelURL):
        normalize_channel_url(text)


def test_parse_entry_public():
    v = parse_entry({"id": "dQw4w9WgXcQ", "title": " Hello ", "duration": 212.0,
                     "upload_date": "20240131"})
    assert v["title"] == "Hello" and v["duration"] == 212
    assert v["upload_date"] == "2024-01-31" and v["availability"] == "public"
    assert v["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert v["thumbnail"].startswith("https://i.ytimg.com/vi/dQw4w9WgXcQ")


def test_parse_entry_states_and_rejects():
    assert parse_entry({"id": "aaaaaaaaaaa", "title": "[Private video]"})["availability"] == "private"
    assert parse_entry({"id": "aaaaaaaaaab", "title": "[Deleted video]"})["availability"] == "deleted"
    assert parse_entry({"id": "aaaaaaaaaac", "title": "x", "availability": "needs_auth"})["availability"] == "needs_auth"
    assert parse_entry({"id": "aaaaaaaaaad", "title": "x", "live_status": "is_upcoming"})["availability"] == "upcoming"
    assert parse_entry({"id": "short", "title": "x"}) is None
    assert parse_entry({"title": "no id"}) is None
    assert parse_entry("junk") is None


def test_parse_entry_timestamp_and_best_thumbnail():
    v = parse_entry({"id": "aaaaaaaaaae", "title": "t", "timestamp": 1700000000,
                     "thumbnails": [{"url": "https://a/small.jpg", "width": 100},
                                    {"url": "https://a/big.jpg", "width": 400},
                                    {"url": "http://insecure/x.jpg", "width": 999}]})
    assert v["upload_date"] == "2023-11-14" and v["thumbnail"] == "https://a/big.jpg"


class FakeYDL:
    def __init__(self, info):
        self.info = info
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False, process=True):
        assert download is False and process is False
        return self.info


def _factory(info):
    return lambda opts: FakeYDL(info)


def test_fetch_large_channel_no_cap_and_nested_tabs():
    entries = [{"id": f"v{i:010d}", "title": f"T{i}", "duration": 60} for i in range(2500)]
    entries.insert(5, {"id": "bad", "title": "not a video"})
    info = {"channel_id": "UC1", "channel": "Chan - Videos",
            "entries": [{"entries": iter(entries[:1000])}, {"entries": entries[1000:]}]}
    seen = []
    res = ChannelParser(_factory(info)).fetch_channel("@chan", on_progress=seen.append)
    assert res.channel_id == "UC1" and res.title == "Chan"
    assert len(res.videos) == 2500 and res.skipped == 1
    assert seen[-1] == 2500


def test_fetch_cancel_and_failures():
    info = {"channel_id": "UC1", "entries": [{"id": f"v{i:010d}", "title": "t"} for i in range(10)]}
    with pytest.raises(ImportCancelled):
        ChannelParser(_factory(info)).fetch_channel("@chan", should_cancel=lambda: True)
    with pytest.raises(ImportFailed):
        ChannelParser(_factory(None)).fetch_channel("@chan")
    with pytest.raises(InvalidChannelURL):
        ChannelParser(_factory(info)).fetch_channel("https://evil.com/@x")

    def boom(opts):
        raise RuntimeError("network down")
    with pytest.raises(ImportFailed):
        ChannelParser(boom).fetch_channel("@chan")
