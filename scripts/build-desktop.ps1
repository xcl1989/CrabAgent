<#
.SYNOPSIS
  Build CrabAgent Desktop App for Windows (.exe installer)
.DESCRIPTION
  1. Build frontend (React/Vite)
  2. Copy static assets into Python package
  3. Compile Python backend with PyInstaller
  4. Copy backend binary to Electron resources
  5. Build Electron NSIS installer
#>
param(
  [ValidateSet("win", "mac")]
  [string]$Target = "win"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host "=== Building CrabAgent Desktop App ($Target) ===" -ForegroundColor Cyan
Write-Host ""

# ── [1/5] Build frontend ──
Write-Host "[1/5] Building frontend..." -ForegroundColor Yellow
Push-Location "$ProjectRoot\frontend"
npm ci --silent 2>$null
if ($LASTEXITCODE -ne 0) { npm install --silent }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
Pop-Location
Write-Host "  Done." -ForegroundColor Green

# ── [2/5] Copy static assets ──
Write-Host "[2/5] Copying static assets..." -ForegroundColor Yellow
$StaticDir = "$ProjectRoot\src\crabagent\static"
New-Item -ItemType Directory -Force -Path $StaticDir | Out-Null
# Clean old assets
Get-ChildItem -Path $StaticDir -Recurse -File | Remove-Item -Force
Copy-Item "$ProjectRoot\frontend\dist\index.html" $StaticDir -Force
Copy-Item "$ProjectRoot\frontend\dist\assets" $StaticDir -Force -Recurse
Write-Host "  Done." -ForegroundColor Green

# ── [3/5] PyInstaller build ──
Write-Host "[3/5] Compiling Python backend with PyInstaller..." -ForegroundColor Yellow
Push-Location $ProjectRoot
pip install pyinstaller -q 2>$null
pyinstaller crabagent.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
Pop-Location
Write-Host "  Done." -ForegroundColor Green

# ── [4/5] Copy backend to Electron resources ──
Write-Host "[4/5] Copying backend to Electron app..." -ForegroundColor Yellow
$ResourcesDir = "$ProjectRoot\electron\resources"
New-Item -ItemType Directory -Force -Path $ResourcesDir | Out-Null

if ($Target -eq "win") {
  # PyInstaller onedir outputs dist/crabagent-backend/ directory
  $BackendDir = "$ProjectRoot\dist\crabagent-backend"
  if (Test-Path "$BackendDir\crabagent-backend.exe") {
    # Copy entire directory (onedir mode has DLLs alongside)
    Copy-Item $BackendDir "$ResourcesDir\crabagent-backend" -Force -Recurse
    Write-Host "  Copied onedir backend bundle" -ForegroundColor Green
  } else {
    throw "Backend binary not found at $BackendDir\crabagent-backend.exe"
  }
} else {
  Copy-Item "$ProjectRoot\dist\crabagent-backend" "$ResourcesDir\crabagent-backend" -Force
}
Write-Host "  Done." -ForegroundColor Green

# ── [5/5] Build Electron app ──
Write-Host "[5/5] Building Electron installer..." -ForegroundColor Yellow
Push-Location "$ProjectRoot\electron"
npm ci --silent 2>$null
if ($LASTEXITCODE -ne 0) { npm install --silent }

$electronArgs = if ($Target -eq "win") { "--win" } else { "--mac" }
npx electron-builder $electronArgs
if ($LASTEXITCODE -ne 0) { throw "Electron build failed" }
Pop-Location
Write-Host "  Done." -ForegroundColor Green

# ── Summary ──
Write-Host ""
Write-Host "=== Build Complete! ===" -ForegroundColor Cyan
$distDir = "$ProjectRoot\electron\dist-electron"
if ($Target -eq "win") {
  $installers = Get-ChildItem -Path $distDir -Filter "*.exe" -ErrorAction SilentlyContinue
  foreach ($inst in $installers) {
    $sizeMB = [math]::Round($inst.Length / 1MB, 1)
    Write-Host "  $($inst.Name) ($sizeMB MB)" -ForegroundColor Green
    Write-Host "  Path: $($inst.FullName)" -ForegroundColor Gray
  }
} else {
  $apps = Get-ChildItem -Path $distDir -Filter "*.dmg" -ErrorAction SilentlyContinue
  foreach ($app in $apps) {
    $sizeMB = [math]::Round($app.Length / 1MB, 1)
    Write-Host "  $($app.Name) ($sizeMB MB)" -ForegroundColor Green
  }
}
