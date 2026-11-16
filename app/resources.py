"""Locate bundled resources and the FFmpeg tools, in dev and inside the frozen .app."""
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts) -> Path:
    return base_dir().joinpath(*parts)


def tool_path(name: str):
    """Bundled ffmpeg/ffprobe; in development fall back to PATH. Returns str or None."""
    cand = resource_path("binaries", name)
    if cand.is_file():
        return str(cand)
    return None if is_frozen() else shutil.which(name)
