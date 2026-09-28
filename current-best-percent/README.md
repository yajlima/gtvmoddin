# Current / Best Percent

A Geode mod for Geometry Dash (Windows, GD 2.2081, Geode v5.10.x) that changes the
in-game percentage to **current% / best%**, for example `12% / 40%`.

- The left number updates live while you play.
- The right number is your saved normal-mode best for the level.
- When you pass your best in a normal run, the right number goes up with you,
  during that same attempt.
- Practice mode, start positions and platformer levels never bump the best
  (the game doesn't save those as normal-mode records either).
- On/off switch: Geode menu -> Current / Best Percent -> settings -> **Enabled**.

The text replaces the game's own percentage label, so the game's
**Show Percentage** option has to be on.

## Build on Windows

One-time setup:

1. Install **Build Tools for Visual Studio 2022** (or newer) with the
   *Desktop development with C++* workload (MSVC + Windows SDK).
2. Install **CMake 3.29+** (add it to PATH), **LLVM (clang)** and **Ninja**,
   e.g. with Scoop: `scoop install cmake llvm ninja`
3. Install the Geode CLI: `winget install GeodeSDK.GeodeCLI`
   (or `scoop bucket add extras` then `scoop install geode-sdk-cli`)
4. Point the CLI at your game: `geode config setup`
5. Install the SDK on the version this mod targets, then its prebuilt binaries:

   ```
   geode sdk install
   geode sdk update v5.10.1
   geode sdk install-binaries
   ```

   Close and reopen the terminal afterwards so `GEODE_SDK` is set.

Build (from this folder):

```
geode build --ninja -- -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
```

The package ends up at `build\yajlima.current-best-percent.geode`. With a CLI
profile set up, the build also copies it into your game's mods folder.

If you'd rather use a newer Geode SDK, change `"geode"` in `mod.json` to that
version (the major.minor has to match the installed SDK).

## Install

Copy `yajlima.current-best-percent.geode` into
`<Geometry Dash folder>\geode\mods\` (for Steam that's usually
`C:\Program Files (x86)\Steam\steamapps\common\Geometry Dash\geode\mods\`),
then restart the game.
