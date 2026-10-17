#!/usr/bin/env bash
# Controles de calidad en Linux (los mismos que calidad.ps1 en Windows):
#   1. ruff  (estilo, errores probables y seguridad)
#   2. mypy  (tipos en la logica)
#   3. pytest con cobertura minima (ver fail_under en pyproject.toml)
# Uso:  ./calidad.sh
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3  # integracion continua: Python del sistema

echo "-- ruff"
"$PY" -m ruff check . || { echo "ruff encontro problemas."; exit 1; }
echo "-- mypy"
"$PY" -m mypy || { echo "mypy encontro errores de tipos."; exit 1; }
echo "-- pruebas y cobertura"
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q -p no:cacheprovider --cov --cov-report=term \
    || { echo "Las pruebas fallaron o la cobertura bajo del minimo."; exit 1; }
echo "Calidad OK"
