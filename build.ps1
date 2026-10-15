# Genera el instalador de Sistema Inteligente Offline en un solo paso:
#   1. pruebas (pytest)   2. programa (PyInstaller)   3. instalador (Inno Setup)
# Uso:  .\build.ps1            (todo)
#       .\build.ps1 -SinPruebas
# Resultado: dist\instalador\SistemaDiagnostico-Setup-<version>.exe
param([switch]$SinPruebas)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No se encontro el entorno .venv. Cree uno e instale requirements-dev.txt" }

$version = (Select-String -Path "app\version.py" -Pattern 'VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "== Sistema Inteligente Offline $version ==" -ForegroundColor Cyan

if (-not $SinPruebas) {
    Write-Host "-- Pruebas" -ForegroundColor Cyan
    & $py -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron: no se genera el instalador." }
}

Write-Host "-- Programa (PyInstaller)" -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean --log-level WARN diagnostico.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }

Write-Host "-- Instalador (Inno Setup)" -ForegroundColor Cyan
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "No se encontro Inno Setup 6. Instalelo con: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }

$salida = Get-Item "dist\instalador\SistemaDiagnostico-Setup-$version.exe"
Write-Host ("Listo: {0} ({1:N1} MB)" -f $salida.FullName, ($salida.Length / 1MB)) -ForegroundColor Green
