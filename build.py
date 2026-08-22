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
MAIN_SCRIPT = "port_killer.py"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def read_version():
    """
    The version lives in port_killer.py. Parsed rather than imported so this
    script still runs before psutil/tkinter are installed.
    """
    src = os.path.join(PROJECT_ROOT, MAIN_SCRIPT)
    with open(src, encoding="utf-8") as f:
        for line in f:
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip("\"\'")
    raise SystemExit(f"APP_VERSION nao encontrado em {src}")


APP_VERSION = read_version()

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

    # ensurepip is required to create a functional venv.
    # On Ubuntu/Debian it ships in a separate package (python3.x-venv).
    try:
        import ensurepip  # noqa: F401
    except ImportError:
        install_venv_package()

    print("Creating build venv at .build-venv ...")
    venv.create(VENV_DIR, with_pip=True, clear=True)

    python = os.path.join(VENV_DIR, "bin", "python3")
    if not os.path.exists(python):
        print(f"ERROR: venv Python not found at {python}. Aborting.")
        sys.exit(1)

    print(f"Re-launching build inside venv: {python}\n")
    result = subprocess.run([python, os.path.abspath(__file__)] + sys.argv[1:])
    sys.exit(result.returncode)


def install_venv_package():
    """
    ensurepip ships separately on Debian/Ubuntu. Hardcoding apt broke the build
    outright on Fedora/Arch/openSUSE, so pick the distro's own tool and say
    something useful when there is none.
    """
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    managers = [
        ("apt",    ["sudo", "apt", "install", "-y", f"python{ver}-venv"]),
        ("dnf",    ["sudo", "dnf", "install", "-y", "python3-virtualenv"]),
        ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "python-virtualenv"]),
        ("zypper", ["sudo", "zypper", "install", "-y", "python3-virtualenv"]),
        ("apk",    ["sudo", "apk", "add", "py3-virtualenv"]),
    ]
    for tool, cmd in managers:
        if shutil.which(tool):
            print(f"ensurepip not available. Installing via {tool} ...")
            subprocess.run(cmd, check=True)
            return
    raise SystemExit(
        "ensurepip nao esta disponivel e nenhum gerenciador de pacotes conhecido "
        f"foi encontrado.\nInstale o pacote venv do Python {ver} manualmente e "
        "rode o build de novo.")


def clean(deep=False):
    # AppDir is staging: leftovers from an earlier build would be packed into
    # the next AppImage.
    targets = ["build", "dist", os.path.join("installer", "linux", "AppDir")]
    if deep:
        targets.append(os.path.join("installer", "windows", "Output"))
        # Never delete the venv we are currently running from.
        if os.path.abspath(sys.prefix) != os.path.abspath(VENV_DIR):
            targets.append(VENV_DIR)
    for d in targets:
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
    run([iscc, f"/DAppVersion={APP_VERSION}",
         os.path.join("installer", "windows", "setup.iss")])
    print(f"\nInstaller: {output_dir}\\PortKiller_Setup_{APP_VERSION}.exe")


# ── Linux ─────────────────────────────────────────────────────────────────────

def build_linux_appimage():
    src = os.path.join("installer", "linux")
    appdir = os.path.join(src, "AppDir")
    if os.path.exists(appdir):
        shutil.rmtree(appdir)

    bin_dir = os.path.join(appdir, "usr", "bin")
    icon_dir = os.path.join(appdir, "usr", "share", "icons", "hicolor", "256x256", "apps")
    apps_dir = os.path.join(appdir, "usr", "share", "applications")
    for d in (bin_dir, icon_dir, apps_dir):
        os.makedirs(d, exist_ok=True)

    shutil.copy(f"dist/{APP_NAME}", os.path.join(bin_dir, APP_NAME))
    os.chmod(os.path.join(bin_dir, APP_NAME), 0o755)

    desktop = os.path.join(src, "port_killer.desktop")
    icon = os.path.join(src, "port_killer.png")

    # appimagetool resolves the .desktop's Icon= key against the AppDir root
    # and aborts when it finds nothing, so the icon has to sit there too —
    # the hicolor copy is what desktop environments pick up after install.
    shutil.copy(desktop, os.path.join(appdir, "port_killer.desktop"))
    shutil.copy(desktop, os.path.join(apps_dir, "port_killer.desktop"))
    shutil.copy(icon, os.path.join(appdir, "port_killer.png"))
    shutil.copy(icon, os.path.join(icon_dir, "port_killer.png"))

    shutil.copy(os.path.join(src, "AppRun"), os.path.join(appdir, "AppRun"))
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

    # Both tools take a *folder* whose contents become the volume root. Passing
    # the .app itself put Contents/ at the root instead of the app, and broke
    # create-dmg's --app-drop-link. Stage the bundle inside a folder first.
    staging = os.path.join("build", "dmg")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    shutil.copytree(app_path, os.path.join(staging, f"{APP_NAME}.app"),
                    symlinks=True)          # .app bundles rely on symlinks

    if shutil.which("create-dmg"):
        run([
            "create-dmg",
            "--volname", "Port Killer",
            "--window-pos", "200", "120",
            "--window-size", "600", "400",
            "--icon-size", "100",
            "--icon", f"{APP_NAME}.app", "175", "150",
            "--app-drop-link", "425", "150",
            dmg_path,
            staging,
        ])
    else:
        # hdiutil is built into macOS — no extra install needed
        run([
            "hdiutil", "create",
            "-volname", "Port Killer",
            "-srcfolder", staging,
            "-ov", "-format", "UDZO",
            dmg_path,
        ])
    shutil.rmtree(staging, ignore_errors=True)

    print(f"\nDMG: {dmg_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build Port Killer installers")
    parser.add_argument("--clean", action="store_true",
                        help="Remove build artifacts (and the build venv) and exit")
    args = parser.parse_args()

    # Every path below is relative to the project; running `python /x/build.py`
    # from elsewhere used to fail on requirements.txt and the .spec.
    os.chdir(PROJECT_ROOT)

    if args.clean:
        clean(deep=True)
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
