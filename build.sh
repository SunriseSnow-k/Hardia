#!/usr/bin/env bash
# Genera el paquete de Sistema Inteligente Offline para Linux en un solo paso:
#   1. calidad (ruff, mypy, pruebas con cobertura)   2. programa (PyInstaller)   3. paquete .tar.gz
# Uso:  ./build.sh              (todo)
#       ./build.sh --sin-pruebas
# Resultado: dist/instalador/SistemaDiagnostico-<version>-linux-<arquitectura>.tar.gz
# (dentro: el programa, instalar.sh, desinstalar.sh y LEAME.txt). El programa queda en dist/linux y
# lo intermedio en build/linux: no pisa lo generado en Windows. Debe ejecutarse en Linux: el
# programa funciona en distribuciones con una glibc igual o más nueva que la de este equipo, así
# que conviene generarlo en la distribución más antigua que se quiera admitir (p. ej. Ubuntu 22.04).
set -euo pipefail
cd "$(dirname "$0")"
# Python: el de la variable PY, el del entorno virtual activo, el de .venv o el del sistema
if [ -z "${PY:-}" ]; then
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then PY="$VIRTUAL_ENV/bin/python"
    elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
    else PY=python3; fi
fi
"$PY" -c "import PyInstaller, PySide6" 2>/dev/null \
    || { echo "Falta PyInstaller o PySide6 en $PY. Instale requirements-dev.txt en el entorno virtual."; exit 1; }
export PY  # calidad.sh usa el mismo Python

VERSION=$(sed -n 's/^VERSION *= *"\(.*\)"/\1/p' app/version.py)
ARQ=$(uname -m)
echo "== Sistema Inteligente Offline $VERSION (Linux $ARQ) =="

if [ "${1:-}" != "--sin-pruebas" ]; then
    echo "-- Calidad"
    bash ./calidad.sh
fi

echo "-- Programa (PyInstaller)"
SALIDA_LINUX=dist/linux
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$SALIDA_LINUX" --workpath build/linux \
    diagnostico.spec
[ -x "$SALIDA_LINUX/Colector/Colector" ] || { echo "PyInstaller no genero el colector."; exit 1; }
[ -x "$SALIDA_LINUX/SistemaDiagnostico/SistemaDiagnostico" ] || { echo "PyInstaller no genero el programa."; exit 1; }
# El colector portatil viaja dentro del programa: desde Escanear se copia a la memoria USB
mkdir -p "$SALIDA_LINUX/Colector/Resultados"
# colector.sh avisa en el PC del cliente si su glibc es más antigua que la de este equipo
ldd --version | head -n 1 | grep -oE '[0-9]+\.[0-9]+$' > "$SALIDA_LINUX/Colector/glibc-minima.txt"
rm -rf "$SALIDA_LINUX/SistemaDiagnostico/Colector"
cp -r "$SALIDA_LINUX/Colector" "$SALIDA_LINUX/SistemaDiagnostico/Colector"
echo "Colector portatil: $(du -sh "$SALIDA_LINUX/Colector" | cut -f1) (tambien en $SALIDA_LINUX/Colector)"

echo "-- Prueba rapida de lo empaquetado"
PRUEBA=$(mktemp -d)
"$SALIDA_LINUX/Colector/Colector" "$PRUEBA" --sin-prueba --sin-pausa >/dev/null \
    && ls "$PRUEBA"/*.diag >/dev/null 2>&1 || { echo "El colector empaquetado no genero el .diag."; exit 1; }
rm -rf "$PRUEBA"
printf '' | "$SALIDA_LINUX/SistemaDiagnostico/SistemaDiagnostico" --ayudante-root | grep -q '"listo"' \
    || { echo "El ayudante con permisos empaquetado no responde."; exit 1; }

echo "-- Paquete (.tar.gz)"
NOMBRE="SistemaDiagnostico-$VERSION"
rm -rf "dist/instalador/$NOMBRE"
mkdir -p "dist/instalador/$NOMBRE"
cp -r "$SALIDA_LINUX/SistemaDiagnostico" "dist/instalador/$NOMBRE/"
cp linux/instalar.sh linux/desinstalar.sh linux/LEAME.txt "dist/instalador/$NOMBRE/"
# El instalador compara con la glibc del equipo destino (el programa no funciona con una más antigua)
cp "$SALIDA_LINUX/Colector/glibc-minima.txt" "dist/instalador/$NOMBRE/"
chmod +x "dist/instalador/$NOMBRE/"*.sh
SALIDA="dist/instalador/$NOMBRE-linux-$ARQ.tar.gz"
tar -C dist/instalador -czf "$SALIDA" "$NOMBRE"
rm -rf "dist/instalador/$NOMBRE"
echo "Listo: $SALIDA ($(du -h "$SALIDA" | cut -f1))"
