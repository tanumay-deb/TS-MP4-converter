@echo off
REM Build the standalone .exe via build.ps1, which fetches the bundled
REM ffmpeg/ffprobe + UPX, builds from TSConverter.spec, and runs --selftest.
REM Pass-through args, e.g.:  build.bat -Installer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
