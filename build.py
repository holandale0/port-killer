#!/usr/bin/env python3
"""
Build script for Port Killer installers.

Usage:
    python build.py              # build for current platform
    python build.py --clean      # remove build artifacts and exit

Requirements per platform:
    All:     pip install pyinstaller psutil
    Windows: Inno Setup 6  ->  https://jrsoftware.org/isdl.php
    Linux:   appimagetool  ->  https://github.com/AppImage/AppImageKit/releases
    macOS:   hdiutil (built-in) or brew install create-dmg
"""

import sys
import os
import subprocess
import shutil
import platform
import argparse
import venv

APP_NAME = "PortKiller"
APP_VERSION = "1.0.0"
MAIN_SCRIPT = "port_killer.py"

INNO_SETUP_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


VENV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".build-venv")


def run(cmd, **kwargs):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def ensure_venv():
    """
    On Linux/macOS with PEP 668 (Ubuntu 23.04+, Debian 12+), pip refuses to
    install system-wide. Automatically create an isolated venv and re-run this
    script inside it so the rest of the build works without --break-system-packages.
    """
    if sys.prefix != sys.base_prefix:
        return  # already inside a venv, nothing to do

    if not sys.platform.startswith("linux") and sys.platform != "darwin":
        return  # Windows handles this differently

    print("Detected externally-managed Python. Creating build venv at .build-venv ...")
    venv.create(VENV_DIR, with_pip=True, clear=False)

    python = os.path.join(VENV_DIR, "bin", "python3")
    print(f"Re-launching build inside venv: {python}\n")
    result = subprocess.run([python, os.path.abspath(__file__)] + sys.argv[1:])
    sys.exit(result.returncode)


def clean():
    for d in ["build", "dist"]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Removed {d}/")


def install_deps():
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def build_executable():
    """Bundle Python + psutil + app into a single executable using PyInstaller."""
    run([sys.executable, "-m", "PyInstaller", "--clean", "port_killer.spec"])


# ── Windows ──────────────────────────────────────────────────────────────────

def build_windows_installer():
    iscc = next((p for p in INNO_SETUP_PATHS if os.path.exists(p)), shutil.which("iscc"))
    if not iscc:
        print("\nInno Setup not found — skipping installer creation.")
        print("Download from: https://jrsoftware.org/isdl.php")
        print(f"Standalone exe: dist\\{APP_NAME}.exe")
        return

    output_dir = os.path.join("installer", "windows", "Output")
    os.makedirs(output_dir, exist_ok=True)
    run([iscc, os.path.join("installer", "windows", "setup.iss")])
    print(f"\nInstaller: {output_dir}\\PortKiller_Setup_{APP_VERSION}.exe")


# ── Linux ─────────────────────────────────────────────────────────────────────

def build_linux_appimage():
    appdir = os.path.join("installer", "linux", "AppDir")
    bin_dir = os.path.join(appdir, "usr", "bin")
    os.makedirs(bin_dir, exist_ok=True)

    shutil.copy(f"dist/{APP_NAME}", os.path.join(bin_dir, APP_NAME))
    os.chmod(os.path.join(bin_dir, APP_NAME), 0o755)

    shutil.copy(
        os.path.join("installer", "linux", "port_killer.desktop"),
        os.path.join(appdir, "port_killer.desktop"),
    )
    shutil.copy(
        os.path.join("installer", "linux", "AppRun"),
        os.path.join(appdir, "AppRun"),
    )
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)

    appimagetool = shutil.which("appimagetool")
    if not appimagetool:
        print("\nappimagetool not found — skipping AppImage creation.")
        print("Download from: https://github.com/AppImage/AppImageKit/releases")
        print(f"Standalone binary: dist/{APP_NAME}")
        return

    arch = platform.machine()
    out = f"dist/PortKiller-{APP_VERSION}-{arch}.AppImage"
    env = {**os.environ, "ARCH": arch}
    run([appimagetool, appdir, out], env=env)
    os.chmod(out, 0o755)
    print(f"\nAppImage: {out}")


# ── macOS ─────────────────────────────────────────────────────────────────────

def build_macos_dmg():
    app_path = f"dist/{APP_NAME}.app"
    dmg_path = f"dist/PortKiller-{APP_VERSION}.dmg"

    if not os.path.exists(app_path):
        print(f"\n.app bundle not found at {app_path}")
        return

    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    if shutil.which("create-dmg"):
        run([
            "create-dmg",
            "--volname", "Port Killer",
            "--window-pos", "200", "120",
            "--window-size", "600", "400",
            "--icon-size", "100",
            "--app-drop-link", "425", "150",
            dmg_path,
            app_path,
        ])
    else:
        # hdiutil is built into macOS — no extra install needed
        run([
            "hdiutil", "create",
            "-volname", "Port Killer",
            "-srcfolder", app_path,
            "-ov", "-format", "UDZO",
            dmg_path,
        ])

    print(f"\nDMG: {dmg_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build Port Killer installers")
    parser.add_argument("--clean", action="store_true", help="Remove build artifacts and exit")
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    ensure_venv()  # no-op on Windows or when already inside a venv

    print(f"Building Port Killer v{APP_VERSION} on {sys.platform} ({platform.machine()})")
    print("=" * 60)

    install_deps()
    clean()
    build_executable()

    if sys.platform == "win32":
        build_windows_installer()
    elif sys.platform.startswith("linux"):
        build_linux_appimage()
    elif sys.platform == "darwin":
        build_macos_dmg()
    else:
        print(f"Platform '{sys.platform}' not supported.")
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
