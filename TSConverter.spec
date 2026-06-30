# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

import os

_ICON = os.path.join(SPECPATH, 'assets', 'icon.ico')
_BIN = os.path.join(SPECPATH, 'bin')

datas = []
binaries = []
hiddenimports = []
if os.path.exists(_ICON):
    datas += [(_ICON, 'assets')]
# Bundle the shared ffmpeg + ffprobe executables (build.ps1 fetches them) as
# binaries, at the bundle root. PyInstaller analyses each exe and pulls in its
# av*.dll dependencies once — adding the DLLs ourselves would duplicate them.
# tsconverter.media.ffmpeg resolves these via sys._MEIPASS at runtime.
for _exe in ('ffmpeg.exe', 'ffprobe.exe'):
    _p = os.path.join(_BIN, _exe)
    if os.path.isfile(_p):
        binaries += [(_p, '.')]
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sv_ttk')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The frozen app uses the bundled shared ffmpeg/ffprobe; don't also pull in
    # imageio-ffmpeg's 83MB binary (it's only a dev/source fallback).
    excludes=['imageio_ffmpeg'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TSConverter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON if os.path.exists(_ICON) else None,
)
