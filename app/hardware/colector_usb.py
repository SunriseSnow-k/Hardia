"""Prepara una memoria USB con el colector portátil (Colector.exe en Windows, Colector en Linux).

El instalador trae el colector en la subcarpeta Colector del programa (build.ps1 lo genera con
PyInstaller y lo copia allí). Preparar el USB es copiar esa carpeta a <unidad>\\Colector junto
con un archivo de instrucciones. Los escaneos se guardan en <unidad>\\Colector\\Resultados, donde
la pantalla Escanear los busca; al actualizar el colector esa carpeta se conserva.

El colector es del mismo sistema que el programa: el de Windows escanea PCs con Windows y el de
Linux, PCs con Linux. En Linux se agrega colector.sh: las memorias FAT32/exFAT suelen montarse sin
permiso de ejecución, así que el lanzador pide sudo y, si hace falta, ejecuta una copia temporal.
"""
import shutil
import sys
from pathlib import Path

from app.plataforma import ES_WINDOWS, ejecutable

from .diag_file import CARPETA_COLECTOR, CARPETA_RESULTADOS

CARPETA = CARPETA_COLECTOR
EXE = ejecutable("Colector")
LANZADOR = "colector.sh"  # solo Linux
INSTRUCCIONES = "LEAME - Colector.txt"
TEXTO_WINDOWS = """COLECTOR DE DIAGNÓSTICO

En el PC del cliente (con Windows):
  1. Conecte esta memoria USB.
  2. Abra la carpeta Colector y ejecute Colector.exe.
  3. Acepte la solicitud de permisos de administrador (sin ellos no se leen
     temperaturas, ventiladores ni el estado SMART de los discos).
  4. Espere a que termine el escaneo: verá un resumen de la salud del equipo.
  5. Si lo desea, acepte la prueba de rendimiento (unos 2 minutos: mide el
     procesador y la velocidad de los discos, solo lectura). Conviene tener el
     cargador conectado y los programas cerrados.
  6. El archivo .diag queda en la carpeta Colector\\Resultados de esta memoria.

El colector no instala nada ni guarda datos en el PC del cliente.

En el taller:
  Conecte la memoria y abra Escanear → Importar desde USB.
"""
TEXTO_LINUX = """COLECTOR DE DIAGNÓSTICO (Linux)

En el PC del cliente (con Linux):
  1. Conecte esta memoria USB y abra una terminal en la carpeta Colector
     (clic derecho en la carpeta → «Abrir en una terminal»).
  2. Ejecute:  sh colector.sh
  3. Escriba la contraseña de sudo cuando se la pida (sin ella no se leen el
     número de serie, los módulos de RAM ni el estado SMART de los discos).
     Para el SMART conviene tener instalado smartmontools.
  4. Espere a que termine el escaneo: verá un resumen de la salud del equipo.
  5. Si lo desea, acepte la prueba de rendimiento (unos 2 minutos: mide el
     procesador y la velocidad de los discos, solo lectura). Conviene tener el
     cargador conectado y los programas cerrados.
  6. El archivo .diag queda en la carpeta Colector/Resultados de esta memoria.

El colector no instala nada en el PC del cliente (si la memoria no permite
ejecutar programas, usa una copia temporal que se borra al terminar).

En el taller:
  Conecte la memoria y abra Escanear → Importar desde USB.
"""
TEXTO_INSTRUCCIONES = TEXTO_WINDOWS if ES_WINDOWS else TEXTO_LINUX
SCRIPT_LINUX = r"""#!/bin/sh
# Colector de diagnóstico: escanea este equipo y guarda el .diag en Resultados (junto a este archivo).
# Uso:  sh colector.sh
DIR=$(cd "$(dirname "$0")" && pwd)
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    echo "El colector necesita permisos de administrador (sudo) para leer todos los datos."
    exec sudo sh "$DIR/colector.sh" "$@"
fi
# El colector funciona con una glibc igual o más nueva que la del equipo donde se generó
if [ -f "$DIR/glibc-minima.txt" ] && command -v ldd >/dev/null 2>&1; then
    MINIMA=$(cat "$DIR/glibc-minima.txt")
    ACTUAL=$(ldd --version 2>/dev/null | head -n 1 | grep -oE '[0-9]+\.[0-9]+$')
    if [ -n "$ACTUAL" ] && [ "$(printf '%s\n%s\n' "$MINIMA" "$ACTUAL" | sort -V | head -n 1)" != "$MINIMA" ]; then
        echo "Este Linux es demasiado antiguo para el colector (tiene glibc $ACTUAL; se necesita $MINIMA o más nueva)."
        echo "En el taller, genere el programa con build.sh en una distribución más antigua."
        exit 1
    fi
fi
mkdir -p "$DIR/Resultados"
if [ -x "$DIR/Colector" ]; then
    exec "$DIR/Colector" "$DIR/Resultados" "$@"
fi
# Memoria sin permiso de ejecución (FAT32/exFAT): copia temporal que se borra al terminar
TMP=$(mktemp -d) || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM
for f in "$DIR"/*; do
    [ "$(basename "$f")" = "Resultados" ] || cp -r "$f" "$TMP/"
done
chmod +x "$TMP/Colector"
"$TMP/Colector" "$DIR/Resultados" "$@"
"""


def origen() -> Path:
    """Carpeta del colector que acompaña al programa: junto al ejecutable instalado o, en
    desarrollo, la que deja build.ps1 en dist\\Colector (build.sh en dist/linux/Colector)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CARPETA
    dist = Path(__file__).resolve().parents[2] / "dist"
    return dist / CARPETA if ES_WINDOWS else dist / "linux" / CARPETA


def disponible(carpeta: Path | None = None) -> bool:
    return ((carpeta or origen()) / EXE).is_file()


def _tamano(carpeta: Path) -> int:
    """Tamaño del programa, sin contar los escaneos de Resultados."""
    return sum(f.stat().st_size for f in carpeta.rglob("*")
               if f.is_file() and f.relative_to(carpeta).parts[0] != CARPETA_RESULTADOS)


def preparar(unidad, carpeta: Path | None = None) -> Path:
    """Copia el colector a <unidad>\\Colector (reemplaza una versión anterior, conservando los
    escaneos de Resultados) y deja las instrucciones en la raíz. Devuelve lo que hay que ejecutar en
    el PC del cliente: Colector.exe en Windows, colector.sh en Linux."""
    fuente = carpeta or origen()
    if not disponible(fuente):
        raise FileNotFoundError("El colector no está incluido en esta instalación. "
                                "Reinstale el programa con la versión más reciente.")
    unidad = Path(unidad)
    if not unidad.is_dir():
        raise OSError(f"No se encuentra la unidad {unidad}.")
    destino = unidad / CARPETA
    necesario = _tamano(fuente) - (_tamano(destino) if destino.is_dir() else 0)
    if necesario > shutil.disk_usage(unidad).free:
        raise OSError(f"No hay espacio suficiente en {unidad} "
                      f"(se necesitan {max(necesario, 0) / 1024 ** 2:.0f} MB).")
    temporal = unidad / f"{CARPETA}.nuevo"
    if temporal.exists():
        shutil.rmtree(temporal)
    # se copia aparte: un USB retirado a mitad no deja el colector roto. Nunca se copian escaneos
    # de la carpeta de origen (serían de otros equipos)
    shutil.copytree(fuente, temporal, ignore=lambda carpeta, _n: [CARPETA_RESULTADOS] if Path(carpeta) == fuente else [])
    resultados = destino / CARPETA_RESULTADOS
    if resultados.is_dir():
        resultados.rename(temporal / CARPETA_RESULTADOS)  # los escaneos ya guardados en la memoria se conservan
    else:
        (temporal / CARPETA_RESULTADOS).mkdir()
    if destino.exists():
        shutil.rmtree(destino)
    temporal.rename(destino)
    (unidad / INSTRUCCIONES).write_text(TEXTO_INSTRUCCIONES, encoding="utf-8-sig")
    if ES_WINDOWS:
        return destino / EXE
    lanzador = destino / LANZADOR
    lanzador.write_bytes(SCRIPT_LINUX.encode("utf-8"))  # finales de línea de Unix
    return lanzador
