# ac-ui

Terminal UI for a local Animal Crossing music library, with `mpv` playback, `cava` visualization, local listening stats, and an optional town-tune workflow.

This repository contains code only. It does not include music files, game discs, extracted game assets, decomp sources, soundfonts, or other copyrighted material.

The town-tune integration work here was developed against a local build/setup based on `ACGC-PC-Port`. Naming that repo is fine; distributing extracted assets, renderer data, or audio-pipeline material derived from a personal ISO is not.

## Repo Safety

Keep these out of GitHub:

- personal music/audio libraries
- game discs and extracted game assets
- renderer binaries built from local sources when they depend on local extracted game data
- decomp or reverse-engineering reference files
- generated sample banks, chimes, stats, and local state

The repo is configured to ignore the common local-only paths and media extensions used by `ac-ui`, including `acgc-reference/`, `music/`, `chimes/`, `acgc_engine/`, `town_tune_samples/`, and common audio/disc formats.

## Requirements

Core runtime:

- `python3`
- `mpv`
- `cava`
- `pactl` via PulseAudio or PipeWire Pulse compatibility

Optional:

- `fluidsynth`
- a General MIDI soundfont such as `FluidR3_GM.sf2`
- `figlet`
- `lolcat`
- an `AnimalCrossing` renderer binary on `PATH` or in the local asset root

## Music Library

By default `ac-ui` reads music from:

```text
~/.local/share/ac-terminal-radio/music
```

Expected filenames look like:

```text
14-GCN-normal.mp3
14-NH-rainy.flac
```

Format:

```text
HH-GAME-variant.ext
```

- `HH`: hour folder prefix, `00` through `23`
- `GAME`: short uppercase tag
- `variant`: lowercase slug
- `ext`: currently `mp3` or `flac`

To import files into the library:

```bash
./ac-ui import /path/to/file1.flac /path/to/file2.mp3
```

## Running

Basic run:

```bash
./ac-ui
```

Useful commands:

```bash
./ac-ui --help
./ac-ui tune show
./ac-ui tune play
./ac-ui tune reset
./ac-ui stats
./ac-ui layout-sweep
```

## Audio Pipeline

The default Linux audio routing is:

1. `ac-ui` starts `mpv`.
2. It creates a private null sink with `pactl` when `AC_UI_PRIVATE_SINK=1`.
3. `mpv` plays into that private sink.
4. A PulseAudio/PipeWire loopback sends the sink monitor back to your real output sink.
5. `cava` reads the monitor source so the visualizer tracks the actual playback stream.

This avoids fighting with the desktop default sink and makes the visualizer attach more reliably.

Relevant environment variables:

- `AC_UI_PRIVATE_SINK=1`
- `AC_UI_OUTPUT_SINK=<sink-name>`
- `AC_UI_AUDIO_DEVICE=<mpv-device>`
- `AC_UI_CAVA_INPUT=pulse`
- `AC_UI_CAVA_SOURCE=<monitor-source>`

If you want to bypass the private sink and point directly at a known sink:

```bash
AC_UI_PRIVATE_SINK=0 AC_UI_OUTPUT_SINK=@DEFAULT_SINK@ ./ac-ui
```

If you know the exact Pulse monitor source you want `cava` to use:

```bash
AC_UI_CAVA_INPUT=pulse AC_UI_CAVA_SOURCE=@DEFAULT_MONITOR@ ./ac-ui
```

## Town Tune Rendering

`ac-ui` supports two local-only preview paths for town tunes:

1. game-accurate rendering through an external `AnimalCrossing` renderer
2. fallback rendering from a locally generated note sample bank

The code does not ship the renderer, a disc image, extracted game assets, or note samples.

The local workflow described here was informed by work done against `ACGC-PC-Port`, but this repo only documents the interface and behavior needed by `ac-ui`. It does not redistribute content extracted from an ISO-derived local setup.

### Practical Findings Used By `ac-ui`

These are the implementation-facing findings that shaped the local workflow in this repo:

- the town tune is a fixed 16-step melody
- each step is a 4-bit value
- the packed save representation is one 64-bit value containing 16 nibbles
- the usable step values are `0..15`
- `0..12` are pitched notes
- `13` is the random-note state
- `14` is the hold/rest-like state
- `15` is the off/blank state

That is why `ac-ui` models the tune as 16 symbolic steps and preserves the special non-pitched states instead of treating everything as plain MIDI notes.

For the terminal editor and preview flow, the practical behavior that mattered was:

- full-tune preview is conceptually separate from single-step audition
- the in-game layout is effectively two rows of 8 notes plus an end/confirm target
- the top-of-hour chime is intentionally the town tune melody, not just a nearby sound effect
- imported tune bytes are effectively constrained to nibble-sized values, so higher bits should not be relied on

These findings are documented here so someone building their own lawful local setup can reproduce the behavior without needing the private notes or local reverse-engineering workspace.

### Renderer Path

`ac-ui` looks for the renderer in this order:

1. `AC_UI_ACGC_TOWN_TUNE_DUMPER`
2. `~/.local/share/ac-terminal-radio/acgc_engine/AnimalCrossing-renderer`
3. `AnimalCrossing` on `PATH`

Useful variables:

- `AC_UI_ACGC_TOWN_TUNE_DUMPER`
- `AC_UI_ACGC_DISC_PATH`
- `ACGC_DISC_PATH`
- `AC_UI_ACGC_TOWN_TUNE_ASSET_ROOT`
- `AC_UI_ACGC_TOWN_TUNE_RENDER=1`

Example:

```bash
AC_UI_ACGC_TOWN_TUNE_DUMPER="$HOME/bin/AnimalCrossing" \
AC_UI_ACGC_DISC_PATH="/path/to/local/game.iso" \
./ac-ui
```

If your renderer can run from extracted local assets instead of a disc path, point `AC_UI_ACGC_TOWN_TUNE_ASSET_ROOT` at your local asset directory and omit the disc variable.

### Sample-Bank Fallback

If the game renderer is unavailable, `ac-ui` can preview notes from a local sample bank under:

```text
~/.local/share/ac-terminal-radio/town_tune_samples
```

The expected filenames are note names like:

```text
G3.wav
A3.wav
...
E5.wav
```

This sample bank is local-only and should not be committed.

## Linux Port Notes

The renderer integration used here is intentionally minimal and local:

- `ac-ui` invokes the external binary with `SDL_AUDIODRIVER=dummy` and `SDL_VIDEODRIVER=dummy`
- when using extracted local assets, it runs from the asset-root working directory
- when using a disc image, it passes `--disc <path>`
- for note/tune rendering it uses the renderer's dump-style CLI flow, such as `--dump-town-note` and `--dump-town-values`

Practical constraints we hit while making the local renderer path work:

- the workflow assumes a local renderer binary with a non-interactive CLI surface
- headless SDL settings matter because `ac-ui` is only trying to render/export audio, not launch a playable game session
- the town-tune integration expects either a local extracted-asset setup or a local disc path; the repo does not provide either
- if your renderer/audio export path depends on data you produced from your own ISO, keep that entire asset side local and out of the repo
- if someone attempts to reproduce the exact menu-pointer behavior from the original PC port, they should be aware that the known implementation was built around a 32-bit assumption, not a general 64-bit-safe interface

For `ac-ui` itself, that last point only matters as a portability note. `ac-ui` does not embed that menu code; it only consumes a renderer/export interface provided by the user's own local setup.

That keeps the repository clean: the GitHub repo documents the interface, but each user supplies their own lawful local setup.

## Useful Environment Variables

- `AC_UI_VIS`
- `AC_UI_PRESET`
- `AC_UI_TITLE_ART=0`
- `AC_UI_STATS=1`
- `AC_UI_HOUR_CHIME=/path/to/local/chime.wav`
- `AC_UI_SOUNDFONT=/path/to/local/font.sf2`
- `AC_UI_FLUIDSYNTH=fluidsynth`
- `AC_UI_FLUIDSYNTH_AUDIO=pulseaudio`

## Publishing Checklist

Before pushing:

```bash
git status --short
git ls-files
```

Make sure you are not tracking:

- `acgc-reference/`
- any `music/`, `chimes/`, `town_tune_samples/`, or `acgc_engine/` content
- any `.iso`, `.wav`, `.flac`, `.mp3`, `.ogg`, `.opus`, `.sf2`, `.aif`, `.aiff`
- local stats/state files

If you keep personal notes about the Linux port or reverse-engineering work, keep them outside the tracked repo or in ignored paths only.
