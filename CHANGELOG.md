# Changelog

All notable changes to this project. Releases are also published (with installers)
on the [Releases](https://github.com/tanumay-deb/TS-MP4-converter/releases) page.

## v1.7.6
- Big files show "Finishing…" while the converted file is being written at the end,
  instead of sitting at 100%.
- "If exists: Overwrite" no longer replaces a file that is still waiting in the list
  (for example clip.mp4, added together with clip.mkv). The new file gets a "(1)" name.
- Mac: closing to the tray no longer hides the window when no tray icon can be shown,
  and "Show in folder" works for folders.

## v1.7.5
- Fixed: long recordings no longer fail with "Stalled at 99%" or "Stalled at 100%".
  The app now waits while the finished file is being written.
- Fixed: files with special characters in their name (like ● or Japanese letters) no
  longer show no length or fail with "Verify failed: … no streams found". If version
  1.7.4 left a "….part.mp4" file after that error, the file is fine: remove ".part"
  from its name.

## v1.7.4
- Tell us what you think: click **Send feedback** at the bottom of the window, or go to
  Help → Send feedback. It takes under a minute and is anonymous.
- If you uninstall the app, your browser opens a short form asking why, so we can
  make it better.
- Drag a folder onto the window to add all the videos in it.
- Fixed: two videos with the same name (for example, from different folders) no longer
  overwrite each other.
- Fixed for TV recordings: Fast (remux only) mode works, 5.1 surround sound converts
  to WebM and Opus, and M4A output always has AAC sound, so it plays everywhere.
- When a conversion fails, the message now says why, instead of a generic ffmpeg line.
- Fixed: re-encoded videos now play on phones, TVs and in browsers, even when the
  original is a 10-bit (4K or HDR) recording.
- Fixed: when the drive runs out of space, the app now says so and removes the
  half-written file. Before, it could quietly re-encode the video at lower quality to
  make it fit, even replacing an existing file. If files converting at the same time
  filled the drive, they are retried one at a time, so as many as possible fit.
- "If exists: Overwrite" now keeps your old file until the new one is finished and
  checked. With "Skip", files that already exist show as Skipped, not Failed.
- Fixed: NVIDIA and AMD graphics cards are now detected and used for re-encoding (the
  app used the CPU before). If the card can't encode a video, the CPU finishes it.
- An update no longer starts while a conversion is running, and the app opens again
  if you say No to the Windows permission prompt during an update. The portable
  version opens the download page instead of installing a second copy.
- The window no longer opens off-screen after you unplug a monitor, and it opens
  maximized if you closed it maximized.
- The buttons and status at the bottom of the window no longer disappear when
  thumbnails are on.
- Installing with pipx works again, and on Mac and Linux you can now open converted
  files from the app.

## v1.7.3
- See a small picture of each video in the list: turn on **Show thumbnails** at the
  top right.
- Drag the edges of the column headers to resize the columns. The app remembers your
  widths.
- Faster: previews, the thumbnail gallery and conversions start with much less waiting.
- Previews now work for more .ts files, including some that showed no picture before.
- This **What's new** window appears once after each update. Open it again any time from
  Help → What's new.

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
