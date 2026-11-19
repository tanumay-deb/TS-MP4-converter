# Changelog

All notable changes to this project. Releases are also published (with installers)
on the [Releases](https://github.com/tanumay-deb/TS-MP4-converter/releases) page.

## v1.7.3
- **What's new** screen: release notes pop up once on the first launch of each new
  version (Help → What's new to reread).
- **Show thumbnails** switch: a frame beside every file in the list (remembered).
- File-list **column widths** are adjustable and remembered.
- Much faster installed app: the build no longer UPX-packs ffmpeg (each ffmpeg/ffprobe
  launch was ~3 s slower). The thumbnail gallery now loads 4 files at a time.
- Fix: no thumbnail for junk-header `.ts` files, or for short `.ts` clips with few keyframes.

## v1.7.2
- Add this **CHANGELOG**. No functional changes since v1.7.1.

## v1.7.1
- In-app **self-update** for installed Windows builds: download and run the release
  installer in place (HTTPS, own-host only), then relaunch.

## v1.7.0
- **Conversion analytics** — success rate, output produced, media processed, format/encoder breakdown.
- **Thumbnail gallery** — grid preview of every queued file.
- Smoother window resize (coalesced row refreshes).
- Internal: conversion queue extracted into a UI-agnostic `QueueController`.

## v1.6.1
- **onedir** build — instant startup (no per-launch extraction).

## v1.6.0
- **Multi-format output**: MP4 / MKV / MOV / WebM, plus audio extraction to MP3 / M4A / WAV / FLAC / Opus.
- Broader input formats (mp4, mov, avi, flv, webm, wmv, m4v, mpg, mpeg).
- **Thumbnail preview**, **system tray** (opt-in), pause now suspends the running ffmpeg.

## v1.5.0
- Bundle real **ffmpeg + ffprobe**; structured probing via `ffprobe -print_format json`.
- **Honest GPU detection** (real test-encode; adds macOS videotoolbox).
- Decoupled engine (`convert()` returns a result; no shared mutable state).
- **Retry failed**, **conversion history**, **update checker**, **pause/resume**.

## v1.4.0
- Zero-setup Windows **installer** (Inno Setup) + tag-triggered build pipeline, app icon, `--selftest`.

## v1.3.0
- Handle fake/junk-prefixed `.ts` files (a bogus PNG header glued in front of the real stream).

## v1.0.0 – v1.2.0
- Initial Tkinter converter (.ts/.m2ts/.mts/.mkv → .mp4), GPU acceleration, drag-and-drop,
  parallel jobs, crash-safe queue, output verification, and per-file logs.
