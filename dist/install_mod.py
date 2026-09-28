#!/usr/bin/env python3
"""Install the Current / Best Percent Geode mod into Geometry Dash (Windows).

Put this script next to yajlima.current-best-percent.geode and run it:

    python install_mod.py

It finds your Geometry Dash folder (Steam, including extra Steam libraries),
checks that Geode is installed, and copies the .geode into geode\\mods.

Options:
    --gd-path PATH      Geometry Dash folder (or GeometryDash.exe) if auto-detect misses it
    --geode-file PATH   The .geode file to install, if it isn't next to this script
    --uninstall         Remove the mod instead
    --no-pause          Don't wait for Enter before closing
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

MOD_FILE_NAME = "yajlima.current-best-percent.geode"
GD_EXE = "GeometryDash.exe"
GEODE_DLL = "Geode.dll"


def find_geode_file(explicit):
    if explicit:
        path = Path(explicit.strip('"')).expanduser()
        return path if path.is_file() else None

    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / MOD_FILE_NAME,
        Path.cwd() / MOD_FILE_NAME,
        script_dir / "dist" / MOD_FILE_NAME,
        script_dir / "build" / MOD_FILE_NAME,
        script_dir.parent / "current-best-percent" / "build" / MOD_FILE_NAME,
        Path.cwd() / "build" / MOD_FILE_NAME,
    ]
    return next((path for path in candidates if path.is_file()), None)


def steam_roots():
    roots = []
    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg:
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass

    roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    return roots


def steam_libraries(steam_root):
    libraries = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return libraries


def find_gd_folder():
    seen = set()
    for root in steam_roots():
        for library in steam_libraries(root):
            gd = library / "steamapps" / "common" / "Geometry Dash"
            key = str(gd).lower()
            if key in seen:
                continue
            seen.add(key)
            if (gd / GD_EXE).is_file():
                return gd
    return None


def normalize_gd_path(raw):
    path = Path(raw.strip().strip('"')).expanduser()
    if path.name.lower() == GD_EXE.lower():
        path = path.parent
    return path


def ask_for_gd_folder():
    if not sys.stdin or not sys.stdin.isatty():
        return None
    print("Couldn't find Geometry Dash automatically.")
    raw = input("Paste your Geometry Dash folder (the one with GeometryDash.exe): ")
    return normalize_gd_path(raw) if raw.strip() else None


def gd_is_running():
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GD_EXE}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return GD_EXE.lower() in result.stdout.lower()


def run(args):
    gd = normalize_gd_path(args.gd_path) if args.gd_path else find_gd_folder()
    if gd is None:
        gd = ask_for_gd_folder()
    if gd is None or not (gd / GD_EXE).is_file():
        where = f" ({gd})" if gd else ""
        print(f"ERROR: no {GD_EXE} found{where}. Pass your game folder with --gd-path.")
        return 1
    print(f"Geometry Dash: {gd}")

    mods = gd / "geode" / "mods"
    installed = mods / MOD_FILE_NAME

    if args.uninstall:
        if installed.is_file():
            installed.unlink()
            print(f"Removed {installed}")
        else:
            print("The mod isn't installed, nothing to remove.")
    else:
        if not (gd / GEODE_DLL).is_file():
            print("ERROR: Geode isn't installed in this Geometry Dash folder.")
            print("Install it from https://geode-sdk.org first, then run this again.")
            return 1

        source = find_geode_file(args.geode_file)
        if source is None:
            print(f"ERROR: couldn't find {MOD_FILE_NAME}.")
            print("Put it next to this script, or pass it with --geode-file.")
            return 1
        print(f"Mod file: {source}")

        mods.mkdir(parents=True, exist_ok=True)
        if source.resolve() != installed.resolve():
            shutil.copy2(source, installed)
        print(f"Installed to {installed}")

    if gd_is_running():
        print("Geometry Dash is running - restart it so the change takes effect.")
    elif args.uninstall:
        print("Done.")
    else:
        print("Done. Start Geometry Dash and the mod will load.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Install the Current / Best Percent Geode mod.")
    parser.add_argument("--gd-path", help="Geometry Dash folder or GeometryDash.exe")
    parser.add_argument("--geode-file", help=f"path to {MOD_FILE_NAME}")
    parser.add_argument("--uninstall", action="store_true", help="remove the mod instead")
    parser.add_argument("--no-pause", action="store_true", help="don't wait for Enter before closing")
    args = parser.parse_args()

    try:
        code = run(args)
    except PermissionError as error:
        print(f"ERROR: permission denied ({error.filename}).")
        print("Close Geometry Dash, or run this from a terminal opened as administrator.")
        code = 1

    # Keeps the window open when the script is double-clicked
    if sys.platform == "win32" and not args.no_pause and sys.stdin and sys.stdin.isatty():
        input("\nPress Enter to close...")
    sys.exit(code)


if __name__ == "__main__":
    main()
