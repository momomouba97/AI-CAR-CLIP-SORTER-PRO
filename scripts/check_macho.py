#!/usr/bin/env python3
"""Verify every Mach-O file under PATH has an x86_64 slice whose minimum macOS is <= --min.
Pure Python (no otool), so it runs on any OS. Exit code 1 on any violation."""
import argparse
import os
import struct
import sys

CPU_X86_64, CPU_ARM64 = 0x01000007, 0x0100000C
CPU_NAMES = {CPU_X86_64: "x86_64", CPU_ARM64: "arm64", 7: "i386"}
MH_MAGIC_64 = b"\xcf\xfa\xed\xfe"
FAT_MAGIC = b"\xca\xfe\xba\xbe"


def _slice_minos(f, offset):
    f.seek(offset)
    head = f.read(32)
    if len(head) < 32 or head[:4] != MH_MAGIC_64:
        return None, None
    cpu = struct.unpack("<i", head[4:8])[0] & 0xFFFFFFFF
    ncmds, sizeofcmds = struct.unpack("<II", head[16:24])
    cmds = f.read(sizeofcmds)
    minos, pos = None, 0
    for _ in range(ncmds):
        if pos + 8 > len(cmds):
            break
        cmd, size = struct.unpack("<II", cmds[pos:pos + 8])
        if cmd == 0x32 and pos + 16 <= len(cmds):          # LC_BUILD_VERSION
            platform, v = struct.unpack("<II", cmds[pos + 8:pos + 16])
            if platform == 1:                              # macOS
                minos = (v >> 16, (v >> 8) & 0xFF)
        elif cmd == 0x24 and minos is None and pos + 12 <= len(cmds):   # LC_VERSION_MIN_MACOSX
            v = struct.unpack("<I", cmds[pos + 8:pos + 12])[0]
            minos = (v >> 16, (v >> 8) & 0xFF)
        if size < 8:
            break
        pos += size
    return cpu, minos


def inspect(path):
    """Return {arch_name: minos_tuple_or_None} or None if not a (64-bit) Mach-O."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic == MH_MAGIC_64:
                cpu, minos = _slice_minos(f, 0)
                return {CPU_NAMES.get(cpu, hex(cpu)): minos} if cpu is not None else None
            if magic == FAT_MAGIC:
                n = struct.unpack(">I", f.read(4))[0]
                if not 1 <= n <= 8:          # Java .class files share this magic
                    return None
                entries = [struct.unpack(">iiIII", f.read(20)) for _ in range(n)]
                out = {}
                for cpu, _sub, off, _size, _al in entries:
                    c, minos = _slice_minos(f, off)
                    if c is not None:
                        out[CPU_NAMES.get(c, hex(c))] = minos
                return out or None
    except OSError:
        return None
    return None


def fmt(v):
    return "unknown" if v is None else f"{v[0]}.{v[1]}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--min", default="11.0", help="highest allowed minimum macOS version")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    limit = tuple(int(x) for x in a.min.split("."))
    total, fat, violations, unknown, worst = 0, 0, [], [], (0, 0)
    for root, _dirs, files in os.walk(a.path):
        for name in files:
            p = os.path.join(root, name)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            info = inspect(p)
            if not info:
                continue
            total += 1
            fat += len(info) > 1
            rel = os.path.relpath(p, a.path)
            if "x86_64" not in info:
                violations.append(f"{rel}: no x86_64 slice (has {', '.join(info)})")
                continue
            v = info["x86_64"]
            if v is None:
                unknown.append(rel)
            else:
                worst = max(worst, v)
                if v > limit:
                    violations.append(f"{rel}: x86_64 minos {fmt(v)} > {a.min}")
            if a.verbose:
                print(f"{fmt(v):>8}  {','.join(info):<14} {rel}")
    print(f"Mach-O files: {total}   multi-arch: {fat}   highest x86_64 minos: {fmt(worst)}   limit: {a.min}")
    if unknown:
        print(f"WARNING: {len(unknown)} file(s) without version info, e.g. {unknown[0]}")
    if violations:
        print(f"FAIL: {len(violations)} violation(s):")
        for v in violations[:50]:
            print("  -", v)
        return 1
    print("OK: all Mach-O files have an x86_64 slice within the limit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
