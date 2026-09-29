# Build MonoSpace for Windows: MonoSpace.exe (PyInstaller, onedir) -> MonoSpace-Setup.exe (Inno Setup)
# -> MonoSpace-<version>-portable.zip. Results go to dist\ in the repo.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Needs: .venv with requirements-dev.txt installed (PyInstaller, Pillow, psutil), and Inno Setup 6
# (installed per-user with winget if missing). The PyInstaller and Inno work happens in
# %TEMP%\monospace-build, outside OneDrive: OneDrive locks files while it syncs them, which breaks
# PyInstaller's clean rebuild. Only the two finished downloads are copied into dist\.
param(
    [string]$Version = "",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "No .venv. Run start.bat once, then: .venv\Scripts\python -m pip install -r requirements-dev.txt" }
& $Py -c "import PyInstaller, PIL, psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing build requirements (requirements-dev.txt) ..."
    & $Py -m pip install --disable-pip-version-check -q -r (Join-Path $Root "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements-dev.txt failed" }
}
if (-not $Version) {
    $Version = (& $Py -c "import sys; sys.path.insert(0, r'$Root'); import server; print(server.__version__)").Trim()
}
$Stage = Join-Path $env:TEMP "monospace-build"
$Out = Join-Path $Stage "out"
$Dist = Join-Path $Root "dist"
Write-Host "MonoSpace $Version  (staging: $Stage)"

# 1. icon
& $Py (Join-Path $PSScriptRoot "make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "make_icon.py failed" }

# 2. MonoSpace.exe (onedir)
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force $Out | Out-Null
& $Py -m PyInstaller (Join-Path $PSScriptRoot "monospace.spec") --noconfirm --log-level WARN `
    --distpath (Join-Path $Stage "pyi-dist") --workpath (Join-Path $Stage "pyi-work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$AppDir = Join-Path $Stage "pyi-dist\MonoSpace"
if (-not (Test-Path (Join-Path $AppDir "MonoSpace.exe"))) { throw "MonoSpace.exe was not built" }

# 3. installer
if (-not $SkipInstaller) {
    $Iscc = @((Get-Command iscc.exe -ErrorAction SilentlyContinue | ForEach-Object Source),
              (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
              (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
              (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")) |
            Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $Iscc) {
        Write-Host "Inno Setup not found: installing it (winget, per-user) ..."
        winget install --id JRSoftware.InnoSetup -e --silent --scope user --accept-package-agreements --accept-source-agreements
        $Iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
        if (-not (Test-Path $Iscc)) { throw "Inno Setup install failed; get it from https://jrsoftware.org/isdl.php" }
    }
    & $Iscc /Q "/DSourceDir=$AppDir" "/DOutDir=$Out" "/DAppVersion=$Version" (Join-Path $PSScriptRoot "monospace.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
}

# 4. portable zip: the onedir folder, as MonoSpace\ inside the zip
$Zip = Join-Path $Out "MonoSpace-$Version-portable.zip"
& $Py -c "import shutil, sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2], 'MonoSpace')" $Zip (Join-Path $Stage "pyi-dist")
if ($LASTEXITCODE -ne 0) { throw "zip failed" }

# 5. into dist\
New-Item -ItemType Directory -Force $Dist | Out-Null
Copy-Item (Join-Path $Out "*") $Dist -Force
Write-Host ""
Write-Host "Built (in $Dist):"
Get-ChildItem $Out | ForEach-Object {
    $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "{0,-36} {1,8:N1} MB  sha256 {2}" -f $_.Name, ($_.Length / 1MB), $h
}
Write-Host "Unpacked program (for testing): $AppDir"
