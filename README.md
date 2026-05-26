# TS to MP4 Converter

A desktop app to batch-convert `.ts` / `.m2ts` / `.mts` / `.mkv` video files to `.mp4`, with GPU acceleration, drag-and-drop, parallel jobs, and automatic re-encode fallback for broken sources.

## Features

- **Input formats**: `.ts`, `.m2ts`, `.mts`, `.mkv` — drop them in or use **Add files** / **Add folder** (recursive scan)
- **Three modes**: Fast remux (instant), Auto (remux + re-encode fallback), or full Re-encode
- **GPU acceleration** auto-detected: NVENC / Quick Sync / AMF
- **Parallel conversion** (1–8 simultaneous jobs)
- **Drag-and-drop** files into the window; **drag-to-reorder** the queue
- **Handles broken sources** — auto-falls-back to re-encode when remux stalls
- **Crash-safe queue** — unfinished jobs restored on the next launch
- **Output verification** — every conversion is probed afterwards to flag silently-broken outputs
- **Per-file logs** saved to a `logs/` folder next to the app (right-click → **Open log**)
- **Optional**: delete the source file after a successful conversion
- **Dark/light theme** toggle
- **Cancel any time**, partial outputs cleaned up
- **Per-file stats**: progress %, encoding speed, ETA
- **Persistent settings** in `%APPDATA%\TSConverter\settings.json`

## Install

### Option 1 — Download the `.exe` (easiest)

1. Grab the latest `TSConverter.exe` from the [Releases](https://github.com/tanumay-deb/TS-MP4-converter/releases) page
2. Double-click to run. No Python needed.

### Option 2 — Install with pipx (one-liner)

Requires Python 3.9+ and [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/tanumay-deb/TS-MP4-converter.git
```

Then launch from anywhere:

```bash
ts-mp4-converter
```

### Option 3 — Clone and run

```bash
git clone https://github.com/tanumay-deb/TS-MP4-converter.git
cd TS-MP4-converter
pip install -r requirements.txt
python app.py
```

On Windows you can also just double-click `run.bat`.

## Build the `.exe` yourself

```bash
pip install -r requirements.txt pyinstaller
build.bat
```

Output: `dist\TSConverter.exe` (single file, ~80 MB, ffmpeg bundled inside).

## How it works

| Mode | What ffmpeg does | Speed | Quality | Handles corruption |
|---|---|---|---|---|
| **Fast** | `-c copy` (stream copy) | 100–500× realtime | Lossless | Poorly |
| **Auto** | Try copy, re-encode if it fails | Mixed | Lossless or near-lossless | Yes |
| **Re-encode** | `-c:v h264_nvenc -c:a aac` | 5–30× realtime (GPU) | Slight loss | Yes |

ffmpeg is bundled via [imageio-ffmpeg](https://pypi.org/project/imageio-ffmpeg/) — no system install required.

## Development

```bash
pip install -e .
```

Files:
- `app.py` — Tkinter UI
- `converter.py` — conversion engine (no UI deps)
- `pyproject.toml` — package config + entry points
- `build.bat` — PyInstaller wrapper

## License

MIT