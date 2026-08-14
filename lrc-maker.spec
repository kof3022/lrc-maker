# -*- mode: python ; coding: utf-8 -*-
"""歌词时间戳 · 免安装版打包配置。

构建（在项目根目录下，需先创建 .venv 并安装 requirements.txt）:
    .venv\Scripts\python -m PyInstaller lrc-maker.spec --noconfirm --clean
"""
from PyInstaller.utils.hooks import collect_all

datas = [("web", "web"), ("img", "img")]
binaries = []
hiddenimports = []

for pkg in ("av", "ctranslate2", "tokenizers", "faster_whisper", "huggingface_hub"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

a = Analysis(
    ["server.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LrcMaker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets\\icon.ico"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LrcMaker",
)