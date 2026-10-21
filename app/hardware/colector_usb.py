"""Prepara una memoria USB con el colector portátil (Colector.exe en Windows, Colector en Linux).

El instalador trae el colector en la subcarpeta Colector del programa (build.ps1 lo genera con
PyInstaller y lo copia allí). Preparar el USB es copiar esa carpeta a <unidad>\\Colector junto
con un archivo de instrucciones. Los escaneos se guardan en <unidad>\\Colector\\Resultados, donde
la pantalla Escanear los busca; al actualizar el colector esa carpeta se conserva.

El colector es del mismo sistema que el programa: el de Windows escanea PCs con Windows y el de
Linux, PCs con Linux. Una misma memoria puede llevar los dos, y cada sistema reemplaza solo el suyo:
  Colector/Colector.exe, Colector/_internal   colector de Windows
  Colector/colector.sh, Colector/linux/       colector de Linux
  Colector/Resultados                         escaneos de los dos (se conservan siempre)
Las memorias FAT32/exFAT suelen montarse en Linux sin permiso de ejecución: colector.sh pide sudo
y, si hace falta, ejecuta una copia temporal.
"""
import shutil
import sys
from pathlib import Path

from app.plataforma import ES_WINDOWS, ejecutable

from .diag_file import CARPETA_COLECTOR, CARPETA_RESULTADOS

CARPETA = CARPETA_COLECTOR
EXE = ejecutable("Colector")
LANZADOR = "colector.sh"  # solo Linux
SUBCARPETA_LINUX = "linux"  # el colector de Linux, dentro de Colector (el de Windows va en la raíz)
EXE_WINDOWS = "Colector.exe"
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
BIN="$DIR/linux"
if [ -f "$BIN/glibc-minima.txt" ] && command -v ldd >/dev/null 2>&1; then
    MINIMA=$(cat "$BIN/glibc-minima.txt")
    ACTUAL=$(ldd --version 2>/dev/null | head -n 1 | grep -oE '[0-9]+\.[0-9]+$')
    if [ -n "$ACTUAL" ] && [ "$(printf '%s\n%s\n' "$MINIMA" "$ACTUAL" | sort -V | head -n 1)" != "$MINIMA" ]; then
        echo "Este Linux es demasiado antiguo para el colector (tiene glibc $ACTUAL; se necesita $MINIMA o más nueva)."
        echo "En el taller, genere el programa con build.sh en una distribución más antigua."
        exit 1
    fi
fi
if [ ! -f "$BIN/Colector" ]; then
    echo "No se encontró el colector de Linux en $BIN. Vuelva a preparar la memoria desde el programa."
    exit 1
fi
mkdir -p "$DIR/Resultados"
if [ -x "$BIN/Colector" ]; then
    exec "$BIN/Colector" "$DIR/Resultados" "$@"
fi
# Memoria sin permiso de ejecución (FAT32/exFAT): copia temporal que se borra al terminar
TMP=$(mktemp -d) || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM
cp -r "$BIN"/. "$TMP/"
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


def disponible(carpeta: Path | None = None, windows: bool = ES_WINDOWS) -> bool:
    return ((carpeta or origen()) / (EXE_WINDOWS if windows else "Colector")).is_file()


def _tamano(ruta: Path) -> int:
    if ruta.is_file():
        return ruta.stat().st_size
    return sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) if ruta.is_dir() else 0


def _de_linux(destino: Path) -> list[Path]:
    """Partes del colector de Linux en <unidad>/Colector (también las de la versión anterior, que
    lo dejaba suelto en la raíz de la carpeta)."""
    partes = [destino / SUBCARPETA_LINUX, destino / LANZADOR]
    if (destino / "Colector").is_file():  # versión anterior: Colector/Colector y Colector/_internal
        partes.append(destino / "Colector")
        if not (destino / EXE_WINDOWS).exists():  # _internal es del de Windows si está Colector.exe
            partes += [destino / "_internal", destino / "glibc-minima.txt"]
    return partes


def _de_windows(destino: Path) -> list[Path]:
    """Partes del colector de Windows: todo lo que no es del de Linux ni los escaneos."""
    if not destino.is_dir():
        return []
    ajenas = {p.name for p in _de_linux(destino)} | {CARPETA_RESULTADOS}
    return [p for p in destino.iterdir() if p.name not in ajenas]


def _borrar(ruta: Path) -> None:
    if ruta.is_dir() and not ruta.is_symlink():
        shutil.rmtree(ruta)
    elif ruta.exists() or ruta.is_symlink():
        ruta.unlink()


def _instrucciones(destino: Path) -> str:
    """Instrucciones de los colectores que lleva la memoria."""
    textos = []
    if (destino / EXE_WINDOWS).is_file():
        textos.append(TEXTO_WINDOWS)
    if (destino / SUBCARPETA_LINUX / "Colector").is_file():
        textos.append(TEXTO_LINUX)
    return "\n\n".join(textos) or TEXTO_INSTRUCCIONES


def preparar(unidad, carpeta: Path | None = None, windows: bool = ES_WINDOWS) -> Path:
    """Copia el colector de este sistema a <unidad>\\Colector. Reemplaza solo su versión anterior:
    los escaneos de Resultados y el colector del otro sistema se conservan. Deja las instrucciones
    en la raíz. Devuelve lo que hay que ejecutar en el PC del cliente: Colector.exe en Windows,
    colector.sh en Linux."""
    fuente = carpeta or origen()
    if not disponible(fuente, windows):
        raise FileNotFoundError("El colector no está incluido en esta instalación. "
                                "Reinstale el programa con la versión más reciente.")
    unidad = Path(unidad)
    if not unidad.is_dir():
        raise OSError(f"No se encuentra la unidad {unidad}.")
    destino = unidad / CARPETA
    anteriores = _de_windows(destino) if windows else _de_linux(destino)
    nuevo = _tamano(fuente) - _tamano(fuente / CARPETA_RESULTADOS)
    necesario = nuevo - sum(_tamano(p) for p in anteriores)
    if necesario > shutil.disk_usage(unidad).free:
        raise OSError(f"No hay espacio suficiente en {unidad} "
                      f"(se necesitan {max(necesario, 0) / 1024 ** 2:.0f} MB).")
    destino.mkdir(exist_ok=True)
    # se copia aparte: un USB retirado a mitad no deja el colector roto. Nunca se copian escaneos
    # de la carpeta de origen (serían de otros equipos)
    temporal = unidad / f"{CARPETA}.nuevo"
    _borrar(temporal)
    shutil.copytree(fuente, temporal, ignore=lambda c, _n: [CARPETA_RESULTADOS] if Path(c) == fuente else [])
    for p in anteriores:
        _borrar(p)
    if windows:
        for p in temporal.iterdir():
            p.rename(destino / p.name)
        temporal.rmdir()
    else:
        temporal.rename(destino / SUBCARPETA_LINUX)
    (destino / CARPETA_RESULTADOS).mkdir(exist_ok=True)  # los escaneos ya guardados se conservan
    if not windows:
        (destino / LANZADOR).write_bytes(SCRIPT_LINUX.encode("utf-8"))  # finales de línea de Unix
    (unidad / INSTRUCCIONES).write_text(_instrucciones(destino), encoding="utf-8-sig")
    return destino / (EXE_WINDOWS if windows else LANZADOR)
