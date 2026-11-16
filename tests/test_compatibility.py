import importlib.util
import struct
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "check_macho", Path(__file__).resolve().parent.parent / "scripts" / "check_macho.py")
cm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cm)

X86, ARM = cm.CPU_X86_64, cm.CPU_ARM64


def enc(major, minor=0):
    return (major << 16) | (minor << 8)


def thin(cpu, minos, build_version=True):
    if build_version:
        lc = struct.pack("<IIIIII", 0x32, 24, 1, enc(*minos), 0, 0)
    else:
        lc = struct.pack("<IIII", 0x24, 16, enc(*minos), 0)
    head = struct.pack("<IiiIIIII", 0xFEEDFACF, cpu, 3, 6, 1, len(lc), 0, 0)
    return head + lc + b"\0" * 32


def fat(*slices):
    n = len(slices)
    off = 4096
    entries, body = b"", b""
    for s in slices:
        cpu = struct.unpack("<i", s[4:8])[0]
        entries += struct.pack(">iiIII", cpu, 3, off + len(body), len(s), 12)
        body += s
    return b"\xca\xfe\xba\xbe" + struct.pack(">I", n) + entries + b"\0" * (off - 8 - 20 * n) + body


def write(tmp, name, data):
    p = tmp / name
    p.write_bytes(data)
    return p


def test_inspect_thin_and_fat(tmp_path):
    assert cm.inspect(write(tmp_path, "a", thin(X86, (11, 0)))) == {"x86_64": (11, 0)}
    assert cm.inspect(write(tmp_path, "b", thin(X86, (10, 13), build_version=False))) == {"x86_64": (10, 13)}
    f = write(tmp_path, "c", fat(thin(X86, (10, 15)), thin(ARM, (11, 0))))
    assert cm.inspect(f) == {"x86_64": (10, 15), "arm64": (11, 0)}
    assert cm.inspect(write(tmp_path, "d", b"just text")) is None
    assert cm.inspect(write(tmp_path, "e", b"\xca\xfe\xba\xbe\x00\x00\x00\x41" + b"\0" * 64)) is None  # Java class


def test_checker_passes_within_limit(tmp_path):
    write(tmp_path, "ok1", thin(X86, (11, 0)))
    write(tmp_path, "ok2", fat(thin(X86, (10, 13)), thin(ARM, (11, 0))))
    write(tmp_path, "notmacho", b"hello")
    assert cm.main([str(tmp_path), "--min", "11.0"]) == 0


def test_checker_fails_when_minos_too_high(tmp_path, capsys):
    write(tmp_path, "new", thin(X86, (12, 0)))
    assert cm.main([str(tmp_path), "--min", "11.0"]) == 1
    assert "12.0 > 11.0" in capsys.readouterr().out


def test_checker_fails_without_x86_64_slice(tmp_path, capsys):
    write(tmp_path, "armonly", thin(ARM, (11, 0)))
    assert cm.main([str(tmp_path), "--min", "11.0"]) == 1
    assert "no x86_64 slice" in capsys.readouterr().out


def test_workflow_and_spec_are_consistent():
    root = Path(__file__).resolve().parent.parent
    wf = (root / ".github/workflows/build-macos.yml").read_text()
    assert "runs-on: macos-15-intel" in wf and "macos-13" not in wf.replace("macos-13 was retired", "")
    assert 'MACOSX_DEPLOYMENT_TARGET: "11.0"' in wf
    spec = (root / "YouTubeDownloaderStudio.spec").read_text()
    assert 'target_arch="x86_64"' in spec and '"LSMinimumSystemVersion": "11.0"' in spec
    reqs = (root / "requirements.txt").read_text()
    assert "PySide6_Essentials==6.5.3" in reqs
