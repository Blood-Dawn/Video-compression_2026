# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['../src/utils/svcs_unlock.py'],
    pathex=['../src'],
    binaries=[],
    datas=[('svcs_unlock.ico', '.')],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='SVCS-Unlock',
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
    icon='svcs_unlock.ico',
    codesign_identity=None,
    entitlements_file=None,
)
