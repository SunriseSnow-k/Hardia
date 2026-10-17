#!/usr/bin/env bash
# Genera el paquete de Sistema Inteligente Offline para Linux en un solo paso:
#   1. calidad (ruff, mypy, pruebas con cobertura)   2. programa (PyInstaller)   3. paquete .tar.gz
# Uso:  ./build.sh              (todo)
#       ./build.sh --sin-pruebas
# Resultado: dist/instalador/SistemaDiagnostico-<version>-linux-<arquitectura>.tar.gz
# (dentro: el programa, instalar.sh, desinstalar.sh y LEAME.txt). Debe ejecutarse en Linux: el
# programa funciona en distribuciones con una glibc igual o más nueva que la de este equipo, así
# que conviene generarlo en la distribución más antigua que se quiera admitir (p. ej. Ubuntu 22.04).
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "No se encontro el entorno .venv. Cree uno e instale requirements-dev.txt"; exit 1; }

VERSION=$(sed -n 's/^VERSION *= *"\(.*\)"/\1/p' app/version.py)
ARQ=$(uname -m)
echo "== Sistema Inteligente Offline $VERSION (Linux $ARQ) =="

if [ "${1:-}" != "--sin-pruebas" ]; then
    echo "-- Calidad"
    ./calidad.sh
fi

echo "-- Programa (PyInstaller)"
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN diagnostico.spec
[ -x dist/Colector/Colector ] || { echo "PyInstaller no genero el colector."; exit 1; }
# El colector portatil viaja dentro del programa: desde Escanear se copia a la memoria USB
mkdir -p dist/Colector/Resultados
rm -rf dist/SistemaDiagnostico/Colector
cp -r dist/Colector dist/SistemaDiagnostico/Colector
echo "Colector portatil: $(du -sh dist/Colector | cut -f1) (tambien en dist/Colector)"

echo "-- Paquete (.tar.gz)"
NOMBRE="SistemaDiagnostico-$VERSION"
rm -rf "dist/instalador/$NOMBRE"
mkdir -p "dist/instalador/$NOMBRE"
cp -r dist/SistemaDiagnostico "dist/instalador/$NOMBRE/"
cp linux/instalar.sh linux/desinstalar.sh linux/LEAME.txt "dist/instalador/$NOMBRE/"
chmod +x "dist/instalador/$NOMBRE/"*.sh
SALIDA="dist/instalador/$NOMBRE-linux-$ARQ.tar.gz"
tar -C dist/instalador -czf "$SALIDA" "$NOMBRE"
rm -rf "dist/instalador/$NOMBRE"
echo "Listo: $SALIDA ($(du -h "$SALIDA" | cut -f1))"
