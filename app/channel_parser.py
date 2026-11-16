"""Validate channel URLs and extract the public video list with yt-dlp (metadata only)."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_HANDLE_RE = re.compile(r"^@[\w.\-]{1,100}$")
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_SEGMENT_RE = re.compile(r"^[\w.@\-%]{1,200}$")
_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")


class InvalidChannelURL(ValueError):
    pass


class ImportCancelled(Exception):
    pass


class ImportFailed(Exception):
    pass


def normalize_channel_url(text: str) -> str:
    """Return the canonical https://www.youtube.com/<channel>/videos URL or raise."""
    t = (text or "").strip()
    if not t:
        raise InvalidChannelURL("Enter a channel URL or @handle.")
    if _HANDLE_RE.match(t):
        return f"https://www.youtube.com/{t}/videos"
    if _CHANNEL_ID_RE.match(t):
        return f"https://www.youtube.com/channel/{t}/videos"
    if "://" not in t:
        t = "https://" + t
    p = urlparse(t)
    if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise InvalidChannelURL("Only youtube.com channel links are supported.")
    parts = [s for s in p.path.split("/") if s]
    if not parts:
        raise InvalidChannelURL("This link does not point to a channel.")
    if parts[0].startswith("@"):
        base = parts[:1]
    elif parts[0] in ("channel", "c", "user") and len(parts) >= 2:
        base = parts[:2]
    else:
        raise InvalidChannelURL("This link is not a channel link (use /@handle, /channel/ID, /c/ or /user/).")
    if not all(_SEGMENT_RE.match(s) for s in base):
        raise InvalidChannelURL("The channel link contains invalid characters.")
    return "https://www.youtube.com/" + "/".join(base) + "/videos"


def _availability(entry: dict, title: str) -> str:
    low = title.lower()
    if "[private video]" in low:
        return "private"
    if "[deleted video]" in low:
        return "deleted"
    if entry.get("live_status") in ("is_upcoming",):
        return "upcoming"
    a = entry.get("availability")
    if a in (None, "", "public"):
        return "public"
    return str(a)  # unlisted, private, needs_auth, subscriber_only, premium_only, ...


def _upload_date(entry: dict) -> str:
    d = entry.get("upload_date")
    if isinstance(d, str) and re.fullmatch(r"\d{8}", d):
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    ts = entry.get("timestamp") or entry.get("release_timestamp")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return ""


def _thumbnail(entry: dict, vid: str) -> str:
    best, best_w = "", -1
    for t in entry.get("thumbnails") or []:
        url = t.get("url", "")
        if url.startswith("https://") and (t.get("width") or 0) > best_w:
            best, best_w = url, t.get("width") or 0
    return best or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"


def parse_entry(entry: dict):
    """Convert a yt-dlp flat entry to a storable dict, or None if it is not a video."""
    if not isinstance(entry, dict):
        return None
    vid = entry.get("id")
    if not isinstance(vid, str) or not _VIDEO_ID_RE.match(vid):
        return None
    title = (entry.get("title") or "").strip() or vid
    dur = entry.get("duration")
    return {
        "video_id": vid,
        "title": title,
        "thumbnail": _thumbnail(entry, vid),
        "duration": int(dur) if isinstance(dur, (int, float)) else 0,
        "upload_date": _upload_date(entry),
        "url": f"https://www.youtube.com/watch?v={vid}",  # built locally, never trusted from input
        "availability": _availability(entry, title),
    }


@dataclass
class ChannelResult:
    channel_id: str
    title: str
    url: str
    videos: list = field(default_factory=list)
    skipped: int = 0


def _default_ydl_factory(opts):
    import yt_dlp  # imported lazily so tests / UI start without it
    return yt_dlp.YoutubeDL(opts)


class ChannelParser:
    def __init__(self, ydl_factory=_default_ydl_factory):
        self._factory = ydl_factory

    @staticmethod
    def _flatten(entries):
        for e in entries or []:
            if e is None:
                continue
            if isinstance(e, dict) and e.get("entries") is not None:
                yield from ChannelParser._flatten(e["entries"])
            else:
                yield e

    def fetch_channel(self, url, on_progress=None, should_cancel=None) -> ChannelResult:
        """Fetch every public video entry. No artificial cap on the number of results."""
        canonical = normalize_channel_url(url)
        opts = {
            "quiet": True, "no_warnings": True, "noprogress": True,
            "extract_flat": "in_playlist", "skip_download": True,
            "ignoreerrors": True, "lazy_playlist": True, "socket_timeout": 30,
        }
        try:
            with self._factory(opts) as ydl:
                info = ydl.extract_info(canonical, download=False, process=False)
                if not info:
                    raise ImportFailed("Could not read this channel (not found or not public).")
                channel_id = info.get("channel_id") or info.get("uploader_id") or info.get("id")
                if not channel_id:
                    raise ImportFailed("Could not identify the channel.")
                title = (info.get("channel") or info.get("uploader") or info.get("title") or channel_id)
                title = re.sub(r"\s+-\s+Videos$", "", title).strip()
                result = ChannelResult(channel_id=channel_id, title=title, url=canonical)
                for raw in self._flatten(info.get("entries")):
                    if should_cancel and should_cancel():
                        raise ImportCancelled()
                    video = parse_entry(raw)
                    if video is None:
                        result.skipped += 1
                        continue
                    result.videos.append(video)
                    if on_progress and len(result.videos) % 25 == 0:
                        on_progress(len(result.videos))
                if on_progress:
                    on_progress(len(result.videos))
                return result
        except (ImportCancelled, ImportFailed, InvalidChannelURL):
            raise
        except Exception as exc:  # yt-dlp DownloadError, network errors, ...
            raise ImportFailed(str(exc)) from exc
