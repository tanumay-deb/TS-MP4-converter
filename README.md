# TS to MP4 Converter

A desktop app to batch-convert video files to MP4 (or MKV / MOV / WebM, or extract audio to MP3 / M4A / WAV / FLAC / Opus), with GPU acceleration, drag-and-drop, parallel jobs, and automatic re-encode fallback for broken sources.

## Features

- **Input formats**: `.ts`, `.m2ts`, `.mts`, `.mkv`, `.mp4`, `.mov`, `.avi`, `.flv`, `.webm`, `.wmv`, `.m4v`, `.mpg`, `.mpeg` — drop them in or use **Add files** / **Add folder** (recursive scan)
- **Output formats**: video → **MP4 / MKV / MOV / WebM**; audio → **MP3 / M4A / WAV / FLAC / Opus** (pick from the Format dropdown)
- **Three modes**: Fast remux (instant), Auto (remux + re-encode fallback), or full Re-encode
- **GPU acceleration** auto-detected: NVENC / Quick Sync / AMF
- **Parallel conversion** (1–8 simultaneous jobs)
- **Drag-and-drop** files into the window; **drag-to-reorder** the queue
- **Handles broken sources** — auto-falls-back to re-encode when remux stalls
- **Handles fake/junk-prefixed `.ts`** — files with a bogus header (e.g. a 1×1 PNG glued in front of the real stream) are auto-detected and converted anyway
- **Pause / Resume** — suspends running jobs (and holds queued ones) without cancelling
- **Retry failed** — one button re-runs every failed job
- **Cancel any time**, partial outputs cleaned up
- **Conversion history** — persistent log of past conversions (File → **Conversion history…**)
- **Thumbnail preview** — right-click a file → **Preview**
- **System tray** (opt-in) — close to tray, conversions keep running, with a completion notification
- **Automatic update check** against GitHub Releases (Help → **Check for updates**)
- **Crash-safe queue** — unfinished jobs restored on the next launch
- **Output verification** — every conversion is probed (via ffprobe) to flag silently-broken outputs
- **Per-file logs** saved to a `logs/` folder next to the app (right-click → **Open log**)
- **Optional**: delete the source file after a successful conversion
- **Dark/light theme** toggle
- **Per-file stats**: progress %, encoding speed, ETA
- **Persistent settings** in `%APPDATA%\TSConverter\settings.json`

## Install

### Option 1 — Run the installer (zero-setup, recommended)

1. Download `TSConverter-<version>-setup.exe` from the [Releases](https://github.com/tanumay-deb/TS-MP4-converter/releases) page
2. Run it. It installs to your machine, adds a Start Menu (and optional desktop) shortcut, and registers an uninstaller.
3. Launch from the Start Menu. **No Python and no ffmpeg install needed** — everything is bundled.

Prefer not to install? Grab the `-portable.zip` from the same page, unzip it anywhere, and run `TSConverter.exe` from the folder.

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

## Build it yourself

Everything is driven by `build.ps1` (PowerShell). It fetches a pinned shared
**ffmpeg + ffprobe** build and **UPX**, builds from `TSConverter.spec`, and runs
`TSConverter.exe --selftest` as a smoke check before packaging.

Just the app folder:

```powershell
pip install -r requirements.txt pyinstaller pillow
.\build.ps1            # or: build.bat   (delegates to build.ps1)
```

The app folder **and** the zero-setup installer (needs [Inno Setup 6](https://jrsoftware.org/isdl.php)):

```powershell
.\build.ps1 -Installer
```

Output: `dist\TSConverter\` (an app folder — `TSConverter.exe` plus an `_internal\`
folder with ffmpeg, ffprobe and the rest) and `dist\installer\TSConverter-<version>-setup.exe`.
The onedir layout launches instantly (no per-run extraction).

Pushing a `vX.Y.Z` tag builds both on GitHub Actions and attaches them to the release automatically.

## How it works

| Mode | What ffmpeg does | Speed | Quality | Handles corruption |
|---|---|---|---|---|
| **Fast** | `-c copy` (stream copy) | 100–500× realtime | Lossless | Poorly |
| **Auto** | Try copy, re-encode if it fails | Mixed | Lossless or near-lossless | Yes |
| **Re-encode** | `-c:v h264_nvenc -c:a aac` | 5–30× realtime (GPU) | Slight loss | Yes |

The modes apply per output format: video targets re-encode to the container's codecs
(H.264/AAC for MP4/MKV/MOV, VP9/Opus for WebM); audio targets drop the video and
encode to the chosen codec (e.g. `-vn -c:a libmp3lame` for MP3). The **Format** dropdown
picks the target; remux is used automatically when a stream copy is valid (e.g. AAC → M4A).

The installed / portable app bundles a pinned **GPL [ffmpeg](https://ffmpeg.org/) + ffprobe**
shared build ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/) — includes libx264 / libmp3lame),
so nothing needs to be installed. ffprobe powers structured probing (`ffprobe -print_format json`);
if it is ever unavailable the app falls back to parsing ffmpeg output. Running from source instead
uses [imageio-ffmpeg](https://pypi.org/project/imageio-ffmpeg/) for ffmpeg.

> ffmpeg is licensed under the **GPL v3**; its corresponding source is available from the build
> provider linked above. The rest of this project is MIT (see `LICENSE`).

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest        # fast, mostly mocked; engine/thumbnail tests skip without ffmpeg
python app.py           # run from source
python app.py --selftest    # headless smoke check (ffmpeg, ffprobe, detection, deps)
```

### Architecture

The engine is decoupled from the UI: `Converter.convert(request)` returns a
`ConversionResult` (streaming `ProgressEvent`s) and never touches the UI; the
`QueueController` is the single owner that maps results onto the `Job` view-model.

```
app.py                       # Tkinter UI / view (wires callbacks + buttons)
converter.py                 # engine: Converter.convert(request) -> ConversionResult
tsconverter/
  models.py                  # ConversionRequest / ProgressEvent / ConversionResult / Job / enums
  queue.py                   # QueueController — worker pool, pause/cancel, result -> Job mapping
  history.py                 # persistent conversion history store
  updater.py                 # GitHub Releases update check (stdlib)
  tray.py                    # optional system-tray icon (pystray)
  media/
    ffmpeg.py                # ffmpeg / ffprobe binary resolution
    probe.py                 # ffprobe -print_format json -> MediaInfo (ffmpeg fallback)
    hwaccel.py               # real test-encode HW-encoder detection (+ videotoolbox)
    handlers.py              # output-format registry (mp4/mkv/mov/webm/mp3/m4a/wav/flac/opus)
    thumbnail.py             # frame extraction for previews
    procctl.py               # suspend/resume a running ffmpeg (psutil)
tests/                       # pytest suite
```

### Packaging / CI

- `TSConverter.spec` — PyInstaller build spec (onedir; bundles ffmpeg+ffprobe, UPX-compressed)
- `build.ps1` — fetches ffmpeg/ffprobe + UPX, builds, runs `--selftest`; `-Installer` (Inno Setup), `-Sign`
- `build.bat` — delegates to `build.ps1`
- `installer.iss` — Inno Setup script for the zero-setup installer
- `.github/workflows/ci.yml` — runs the test suite on every push/PR
- `.github/workflows/build.yml` — on a `vX.Y.Z` tag, builds the installer + portable zip and attaches them to the release

## License

MIT (this project). The bundled ffmpeg/ffprobe are GPL — see "How it works" above.