<#
  Build script for TS to MP4 Converter (Windows).

  Usage:
    .\build.ps1                       # build dist\TSConverter.exe
    .\build.ps1 -Installer            # also build the Inno Setup installer
    .\build.ps1 -Installer -Version 1.4.0     # stamp the installer version (CI passes the tag)
    .\build.ps1 -Sign -CertPath x.pfx -CertPass ****   # sign the exe + installer

  Requirements:
    - Python 3.9+ with the project deps:  pip install -r requirements.txt pyinstaller pillow
    - For -Installer:  Inno Setup 6 (iscc.exe on PATH or at the default location)
    - For -Sign:       a code-signing cert (.pfx) and Windows SDK signtool.exe
#>
param(
    [switch]$Installer,
    [switch]$Sign,
    [string]$CertPath,
    [string]$CertPass,
    [string]$Version          # override the installer version (e.g. from a CI tag)
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Ensuring the .ico exists" -ForegroundColor Cyan
if (-not (Test-Path "assets\icon.ico")) {
    if (Test-Path "assets\icon.png") {
        python -c "from PIL import Image; Image.open('assets/icon.png').convert('RGBA').save('assets/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    } else {
        Write-Warning "assets\icon.ico not found and no icon.png to convert; building without a custom icon."
    }
}

Write-Host "==> Ensuring bundled ffmpeg + ffprobe (shared build)" -ForegroundColor Cyan
# imageio-ffmpeg ships only ffmpeg. Bundle a pinned GPL *shared* build instead,
# which includes ffprobe and the encoders we need (libx264, libmp3lame). Small
# exes + shared DLLs keep the size far below a standalone static ffprobe.
$ffVersion = "8.1.2"
$ffName = "ffmpeg-$ffVersion-full_build-shared"
$binDir = "bin"
if ((Test-Path "$binDir\ffmpeg.exe") -and (Test-Path "$binDir\ffprobe.exe")) {
    Write-Host "    already present in $binDir\" -ForegroundColor DarkGray
} else {
    New-Item -ItemType Directory -Force $binDir | Out-Null
    $zip = Join-Path $env:TEMP "$ffName.zip"
    $url = "https://github.com/GyanD/codexffmpeg/releases/download/$ffVersion/$ffName.zip"
    if (-not (Test-Path $zip)) {
        Write-Host "    downloading $url" -ForegroundColor DarkGray
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    }
    $sha = (Get-FileHash $zip -Algorithm SHA256).Hash
    Write-Host "    SHA256 $sha" -ForegroundColor DarkGray
    Write-Host "    ^ verify against https://github.com/GyanD/codexffmpeg/releases/tag/$ffVersion" -ForegroundColor DarkGray
    $tmp = Join-Path $env:TEMP $ffName
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $srcBin = Join-Path $tmp "$ffName\bin"
    Copy-Item (Join-Path $srcBin "ffmpeg.exe")  $binDir -Force
    Copy-Item (Join-Path $srcBin "ffprobe.exe") $binDir -Force
    # Bring the shared DLLs; skip ffplay and its SDL dependency to save space.
    Get-ChildItem $srcBin -Filter *.dll | Where-Object { $_.Name -notlike "SDL2*" } |
        ForEach-Object { Copy-Item $_.FullName $binDir -Force }
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Write-Host "    ffmpeg + ffprobe + DLLs -> $binDir\" -ForegroundColor Green
}

Write-Host "==> Ensuring UPX (compresses the bundled ffmpeg DLLs)" -ForegroundColor Cyan
$upxVersion = "5.2.0"
$upxRoot = Join-Path $PSScriptRoot "tools"
$upxDir = Join-Path $upxRoot "upx-$upxVersion-win64"
if (-not (Test-Path (Join-Path $upxDir "upx.exe"))) {
    try {
        New-Item -ItemType Directory -Force $upxRoot | Out-Null
        $zip = Join-Path $env:TEMP "upx-$upxVersion-win64.zip"
        $url = "https://github.com/upx/upx/releases/download/v$upxVersion/upx-$upxVersion-win64.zip"
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $upxRoot -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Write-Host "    upx -> $upxDir" -ForegroundColor Green
    } catch {
        Write-Warning "UPX fetch failed ($($_.Exception.Message)); building uncompressed (much larger exe)."
        $upxDir = $null
    }
}
$upxArgs = @()
if ($upxDir -and (Test-Path (Join-Path $upxDir "upx.exe"))) { $upxArgs = @("--upx-dir", $upxDir) }

Write-Host "==> Cleaning previous build" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "==> Building with PyInstaller" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean @upxArgs TSConverter.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$exe = "dist\TSConverter\TSConverter.exe"   # onedir layout
if (-not (Test-Path $exe)) { throw "expected $exe was not produced" }

Write-Host "==> Smoke-testing the frozen binary" -ForegroundColor Cyan
# The app is a GUI (windowed) exe; the call operator '&' does not block on those,
# so use Start-Process -Wait to actually get the exit code.
$st = Start-Process -FilePath $exe -ArgumentList '--selftest' -Wait -PassThru -NoNewWindow
if ($st.ExitCode -ne 0) { throw "selftest failed (exit $($st.ExitCode))" }

function Invoke-Sign($target) {
    $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)" }
    & $signtool sign /f $CertPath /p $CertPass /fd SHA256 `
        /tr http://timestamp.digicert.com /td SHA256 $target
    if ($LASTEXITCODE -ne 0) { throw "signing failed for $target" }
}

if ($Sign) {
    if (-not $CertPath) { throw "-Sign requires -CertPath <pfx>" }
    Write-Host "==> Signing the app exe" -ForegroundColor Cyan
    Invoke-Sign $exe
}

if ($Installer) {
    Write-Host "==> Building the Inno Setup installer" -ForegroundColor Cyan
    $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        foreach ($p in @("$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                         "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe")) {
            if (Test-Path $p) { $iscc = $p; break }
        }
    }
    if (-not $iscc -or -not (Test-Path $iscc)) { throw "Inno Setup (iscc.exe) not found" }
    $isccArgs = @()
    if ($Version) { $isccArgs += "/DAppVersion=$Version" }
    & $iscc @isccArgs "installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "installer build failed" }
    if ($Sign) {
        Write-Host "==> Signing the installer" -ForegroundColor Cyan
        Invoke-Sign (Get-ChildItem "dist\installer\*.exe" | Select-Object -First 1).FullName
    }
}

Write-Host "==> Done. Output in dist\" -ForegroundColor Green
