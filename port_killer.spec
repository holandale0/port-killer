# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Version and icons come from the repo, not from copies kept in this file.
APP_VERSION = None
with open("port_killer.py", encoding="utf-8") as _f:
    for _line in _f:
        if _line.startswith("APP_VERSION"):
            APP_VERSION = _line.split("=", 1)[1].strip().strip("\"\'")
            break
if not APP_VERSION:
    raise SystemExit("APP_VERSION nao encontrado em port_killer.py")

_ICONS = {
    "win32":  os.path.join("installer", "windows", "port_killer.ico"),
    "darwin": os.path.join("installer", "macos", "port_killer.icns"),
}
ICON = _ICONS.get(sys.platform)
if ICON and not os.path.exists(ICON):
    ICON = None

# Shipped so the running app can set its own window icon.
_WINDOW_ICON = os.path.join("installer", "linux", "port_killer.png")
DATAS = [(_WINDOW_ICON, ".")] if os.path.exists(_WINDOW_ICON) else []

a = Analysis(
    ['port_killer.py'],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='PortKiller',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='PortKiller',
    )
    app = BUNDLE(
        coll,
        name='PortKiller.app',
        icon=ICON,
        bundle_identifier='com.portkiller.app',
        version=APP_VERSION,
        info_plist={
            'CFBundleName': 'Port Killer',
            'CFBundleDisplayName': 'Port Killer',
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
else:
    # Windows and Linux: single-file executable
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='PortKiller',
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
        icon=ICON,
    )
