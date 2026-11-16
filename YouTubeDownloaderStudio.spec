# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec. Build (on macOS Intel): python -m PyInstaller --noconfirm --clean YouTubeDownloaderStudio.spec
import os
import re
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = "YouTube Downloader Studio"
ROOT = os.path.abspath(SPECPATH)
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', open(os.path.join(ROOT, "app", "__init__.py")).read()).group(1)

hidden = collect_submodules("yt_dlp")
datas = collect_data_files("certifi") + [(os.path.join(ROOT, "resources"), "resources")]
binaries = []
for tool in ("ffmpeg", "ffprobe"):
    p = os.path.join(ROOT, "binaries", tool)
    if os.path.isfile(p):
        binaries.append((p, "binaries"))

EXCLUDES = ["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf",
            "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
            "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets"]

a = Analysis([os.path.join(ROOT, "main.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=EXCLUDES, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="YouTubeDownloaderStudio",
          console=False, argv_emulation=False, target_arch="x86_64", upx=False,
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="YouTubeDownloaderStudio")
icon = os.path.join(ROOT, "resources", "app.icns")
app = BUNDLE(coll, name=APP_NAME + ".app", icon=icon if os.path.isfile(icon) else None,
             bundle_identifier="com.youtubedownloaderstudio.app", version=VERSION,
             info_plist={
                 "CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME,
                 "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                 "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
                 "LSApplicationCategoryType": "public.app-category.utilities",
                 "NSHumanReadableCopyright": "Open source",
             })
