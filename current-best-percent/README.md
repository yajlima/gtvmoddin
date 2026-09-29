# Current / Best Percent

A Geode mod for Geometry Dash on Windows that changes the in-game percentage to
**current% / best%**, for example `12% / 40%`.

- The left number updates live while you play.
- The right number is your saved normal-mode best for the level.
- When you pass your best in a normal run, the right number goes up with you,
  during that same attempt.
- Practice mode, start positions and platformer levels never bump the best
  (the game doesn't save those as normal-mode records either).
- It shows even if the game's own Show Percentage option is off.

## Install (prebuilt)

Pick the file that matches your game (the Geode version is shown at the bottom
of the Geode menu):

| Your setup | File in `dist/` |
| --- | --- |
| GD 2.2081, Geode 5.x | `yajlima.current-best-percent.geode` |
| GD 2.2074, Geode 4.x | `yajlima.current-best-percent-gd2.2074-geode4.geode` |

In the game: Geode button on the main menu -> gear in the bottom-left column
(Geode's own settings) -> **Install From File** (the first click only shows a
warning, click it again) -> pick the file -> restart the game.

Or copy the file into `<Geometry Dash folder>\geode\mods\` (Steam:
`C:\Program Files (x86)\Steam\steamapps\common\Geometry Dash\geode\mods\`) and
restart. `dist/install_mod.py` can do that copy for you.

## Settings

Geode menu -> find **Current / Best Percent** in the installed list -> open it
-> settings button in the bottom left of its popup -> **Enabled**.

## Build on Windows

This project targets the latest Geode SDK (5.10.x, GD 2.2081). The prebuilt
files in `dist/` are the same source built against older SDKs (5.0.1 and
4.10.2) so they load on older Geode installs too.

One-time setup:

1. Install **Build Tools for Visual Studio 2022** (or newer) with the
   *Desktop development with C++* workload (MSVC + Windows SDK).
2. Install **CMake 3.29+** (add it to PATH), **LLVM (clang)** and **Ninja**,
   e.g. with Scoop: `scoop install cmake llvm ninja`
3. Install the Geode CLI: `winget install GeodeSDK.GeodeCLI`
   (or `scoop bucket add extras` then `scoop install geode-sdk-cli`)
4. Point the CLI at your game: `geode config setup`
5. Install the SDK and its prebuilt binaries:

   ```
   geode sdk install
   geode sdk install-binaries
   ```

   Close and reopen the terminal afterwards so `GEODE_SDK` is set.
   `geode sdk version` shows the version you got; if it isn't 5.10.x, change
   `"geode"` in `mod.json` to it (the major.minor has to match).

Build (from this folder):

```
geode build --ninja -- -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
```

The package ends up at `build\yajlima.current-best-percent.geode`. With a CLI
profile set up, the build also copies it into your game's mods folder.
