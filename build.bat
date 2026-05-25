@echo off
REM Build a standalone .exe with PyInstaller.
REM Output: dist\TSConverter.exe
cd /d "%~dp0"

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
)

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name TSConverter ^
    --collect-all imageio_ffmpeg ^
    --collect-all tkinterdnd2 ^
    --collect-all sv_ttk ^
    app.py

echo.
echo Done. See dist\TSConverter.exe
pause
