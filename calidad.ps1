# Controles de calidad del proyecto (los mismos que ejecuta build.ps1 y la integracion continua):
#   1. ruff  (estilo, errores probables y seguridad)
#   2. mypy  (tipos en la logica: datos, servicios, hardware, salud, reportes, IA)
#   3. pytest con cobertura minima (ver fail_under en pyproject.toml)
# Uso:  .\calidad.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }  # integracion continua: Python del sistema

Write-Host "-- ruff" -ForegroundColor Cyan
& $py -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff encontro problemas." }

Write-Host "-- mypy" -ForegroundColor Cyan
& $py -m mypy
if ($LASTEXITCODE -ne 0) { throw "mypy encontro errores de tipos." }

Write-Host "-- pruebas y cobertura" -ForegroundColor Cyan
& $py -m pytest -q -p no:cacheprovider --cov --cov-report=term
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron o la cobertura bajo del minimo." }

Write-Host "Calidad OK" -ForegroundColor Green
