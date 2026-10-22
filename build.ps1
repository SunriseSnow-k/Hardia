# Genera el instalador de Sistema Inteligente Offline en un solo paso:
#   1. calidad (ruff, mypy, pruebas con cobertura)   2. programa (PyInstaller)   3. instalador (Inno Setup)
# Uso:  .\build.ps1               (todo)
#       .\build.ps1 -SinPruebas
#       .\build.ps1 -SoloColector  (solo el colector, para incluirlo en el instalador de Linux)
# Resultado: dist\instalador\SistemaDiagnostico-Setup-<version>.exe
# El instalador incluye el colector de Linux si esta en dist\colectores (Colector-linux.tar.gz,
# generado por build.sh en Linux: ver tools\colectores.py); asi desde Windows se preparan memorias
# USB con los dos colectores.
param([switch]$SinPruebas, [switch]$SoloColector)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No se encontro el entorno .venv. Cree uno e instale requirements-dev.txt" }

$version = (Select-String -Path "app\version.py" -Pattern 'VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "== Sistema Inteligente Offline $version ==" -ForegroundColor Cyan

if (-not $SinPruebas -and -not $SoloColector) {
    Write-Host "-- Calidad" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "calidad.ps1")  # lanza un error (y no se genera el instalador) si algo falla
}

Write-Host "-- Programa (PyInstaller)" -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean --log-level WARN diagnostico.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }
# El colector portatil viaja dentro del programa: desde Escanear se copia a la memoria USB
$colector = "dist\SistemaDiagnostico\Colector"
if (-not (Test-Path "dist\Colector\Colector.exe")) { throw "PyInstaller no genero el colector." }
New-Item -ItemType Directory -Force "dist\Colector\Resultados" | Out-Null  # aqui guarda el colector los .diag
if (Test-Path $colector) { Remove-Item -Recurse -Force $colector }
Copy-Item -Recurse "dist\Colector" $colector
$mb = (Get-ChildItem -Recurse -File $colector | Measure-Object -Sum Length).Sum / 1MB
Write-Host ("Colector portatil: {0:N1} MB (tambien en dist\Colector para copiarlo a mano)" -f $mb)
& $py tools\colectores.py empaquetar windows dist\Colector
if ($LASTEXITCODE -ne 0) { throw "No se pudo empaquetar el colector." }
if ($SoloColector) {
    Write-Host "Listo: dist\colectores\Colector-windows.tar.gz (copielo a dist/colectores en Linux)" -ForegroundColor Green
    exit 0
}
Write-Host "-- Colector de Linux" -ForegroundColor Cyan
& $py tools\colectores.py incluir windows dist\SistemaDiagnostico
if ($LASTEXITCODE -ne 0) { throw "No se pudo incluir el colector de Linux." }

Write-Host "-- Instalador (Inno Setup)" -ForegroundColor Cyan
# Controlador de sensores incluido en el instalador (version y SHA-256 fijos, como el paquete de IA)
$pawnio = "redist\PawnIO_setup.exe"
$pawnioSha = "1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032"
if (-not (Test-Path $pawnio) -or (Get-FileHash $pawnio -Algorithm SHA256).Hash.ToLower() -ne $pawnioSha) {
    throw "Falta $pawnio o no es la version esperada (PawnIO 2.2.0: https://github.com/namazso/PawnIO.Setup/releases/tag/2.2.0)"
}
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
