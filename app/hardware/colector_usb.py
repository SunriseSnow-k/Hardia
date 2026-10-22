"""Prepara una memoria USB con el colector portátil (Colector.exe en Windows, Colector en Linux).

El instalador trae el colector de su sistema en la subcarpeta Colector del programa (build.ps1 o
build.sh lo generan con PyInstaller y lo copian allí) y, si se generó en su sistema, el del otro en
Colectores/<sistema> (ver dist/colectores en build.sh y build.ps1). Así, desde un solo programa se
prepara una memoria con los dos. Preparar el USB es copiar esa carpeta a <unidad>\\Colector junto
con un archivo de instrucciones. Los escaneos se guardan en <unidad>\\Colector\\Resultados, donde
la pantalla Escanear los busca; al actualizar el colector esa carpeta se conserva.

Cada colector escanea solo el sistema en que se ejecuta: el de Windows PCs con Windows y el de Linux
PCs con Linux. Una misma memoria puede llevar los dos, y preparar uno reemplaza solo ese:
  Colector/Colector.exe, Colector/_internal   colector de Windows
  Colector/colector.sh, Colector/linux/       colector de Linux (Colector-Linux.com: doble clic)
  Colector/Resultados                         escaneos de los dos (se conservan siempre)
Las memorias FAT32/exFAT suelen montarse en Linux sin permiso de ejecución: colector.sh pide sudo
y, si hace falta, ejecuta una copia temporal.
"""
import os
import shutil
import sys
from pathlib import Path

from app.plataforma import SISTEMA, ejecutable

from .diag_file import CARPETA_COLECTOR, CARPETA_RESULTADOS, SUBCARPETA_LINUX

CARPETA = CARPETA_COLECTOR
CARPETA_OTROS = "Colectores"  # en el programa: los colectores de los otros sistemas, uno por subcarpeta
SISTEMAS = ("windows", "linux")
NOMBRES = {"windows": "Windows", "linux": "Linux"}
EXE = ejecutable("Colector")
LANZADOR = "colector.sh"  # solo Linux
EXE_WINDOWS = "Colector.exe"
# En la memoria el colector de Linux termina en .com: las memorias FAT32 se montan sin permiso de
# ejecución salvo para .exe, .com y .bat (opción showexec), y así se abre con doble clic
EXE_USB_LINUX = "Colector-Linux.com"
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
  1. Conecte esta memoria USB, abra la carpeta Colector/linux y haga doble
     clic en Colector-Linux.com: se abre una terminal con el colector.
     Si el explorador de archivos no lo abre, abra una terminal en la carpeta
     Colector (clic derecho → «Abrir en una terminal») y ejecute:
         sh colector.sh
  2. Escriba la contraseña de sudo cuando se la pida (sin ella no se leen el
     número de serie, los módulos de RAM ni el estado SMART de los discos).
     Para el SMART conviene tener instalado smartmontools.
  3. Espere a que termine el escaneo: verá un resumen de la salud del equipo.
  4. Si lo desea, acepte la prueba de rendimiento (unos 2 minutos: mide el
     procesador y la velocidad de los discos, solo lectura). Conviene tener el
     cargador conectado y los programas cerrados.
  5. El archivo .diag queda en la carpeta Colector/Resultados de esta memoria.

El colector no instala nada en el PC del cliente (si la memoria no permite
ejecutar programas, usa una copia temporal que se borra al terminar).

En el taller:
  Conecte la memoria y abra Escanear → Importar desde USB.
"""
TEXTO_INSTRUCCIONES = TEXTO_WINDOWS if SISTEMA == "windows" else TEXTO_LINUX
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
EXE="$BIN/Colector-Linux.com"
[ -f "$EXE" ] || EXE="$BIN/Colector"  # memorias preparadas con una versión anterior
if [ ! -f "$EXE" ]; then
    echo "No se encontró el colector de Linux en $BIN. Vuelva a preparar la memoria desde el programa."
    exit 1
fi
mkdir -p "$DIR/Resultados"
if [ -x "$EXE" ]; then
    exec "$EXE" "$DIR/Resultados" "$@"
fi
# Memoria sin permiso de ejecución: copia temporal que se borra al terminar
TMP=$(mktemp -d) || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM
cp -r "$BIN"/. "$TMP/"
NOMBRE=$(basename "$EXE")
chmod +x "$TMP/$NOMBRE"
"$TMP/$NOMBRE" "$DIR/Resultados" "$@"
"""


# Lo que el técnico ejecuta en el PC del cliente, según el sistema del colector
PARA_EJECUTAR = {"windows": EXE_WINDOWS, "linux": LANZADOR}


def como_ejecutar(ruta: Path, sistema: str = SISTEMA) -> str:
    """Instrucción breve para abrir el colector que dejó preparar() en `ruta`."""
    if sistema == "windows":
        return f"ejecute {ruta}"
    return (f"abra {ruta.parent / SUBCARPETA_LINUX} y haga doble clic en {EXE_USB_LINUX} "
            f"(o, en una terminal en {ruta.parent}: sh {ruta.name})")


def origen(sistema: str = SISTEMA) -> Path:
    """Carpeta del colector de `sistema` que acompaña al programa: el de este sistema en Colector y
    el otro en Colectores/<sistema>. En desarrollo, la que deja el build de ese sistema
    (dist\\Colector, dist/linux/Colector) o la traída del otro equipo en dist/colectores/<sistema>."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        return base / CARPETA if sistema == SISTEMA else base / CARPETA_OTROS / sistema
    dist = Path(__file__).resolve().parents[2] / "dist"
    propia = dist / CARPETA if sistema == "windows" else dist / sistema / CARPETA
    return propia if disponible(propia, sistema) else dist / "colectores" / sistema


def disponible(carpeta: Path | None = None, sistema: str = SISTEMA) -> bool:
    return ((carpeta or origen(sistema)) / (EXE_WINDOWS if sistema == "windows" else "Colector")).is_file()


def disponibles() -> list[str]:
    """Sistemas cuyos colectores trae esta instalación (el de este sistema primero)."""
    return [s for s in (SISTEMA, *(x for x in SISTEMAS if x != SISTEMA)) if disponible(sistema=s)]


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


_PARTES = {"windows": _de_windows, "linux": _de_linux}


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
    if any((destino / SUBCARPETA_LINUX / n).is_file() for n in (EXE_USB_LINUX, "Colector")):
        textos.append(TEXTO_LINUX)
    return "\n\n".join(textos) or TEXTO_INSTRUCCIONES


def preparar(unidad, carpeta: Path | None = None, sistema: str = SISTEMA) -> Path:
    """Copia el colector de este sistema a <unidad>\\Colector. Reemplaza solo su versión anterior:
    los escaneos de Resultados y el colector del otro sistema se conservan. Deja las instrucciones
    en la raíz. Devuelve lo que hay que ejecutar en el PC del cliente: Colector.exe en Windows,
    colector.sh en Linux."""
    windows = sistema == "windows"
    fuente = carpeta or origen(sistema)
    if not disponible(fuente, sistema):
        raise FileNotFoundError("El colector no está incluido en esta instalación. "
                                "Reinstale el programa con la versión más reciente.")
    unidad = Path(unidad)
    if not unidad.is_dir():
        raise OSError(f"No se encuentra la unidad {unidad}.")
    destino = unidad / CARPETA
    anteriores = _PARTES[sistema](destino)
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
    no_copiar = [CARPETA_RESULTADOS, "Colector"] if sistema == "linux" else [CARPETA_RESULTADOS]

    def ignorar(carpeta, nombres):
        rotos = [n for n in nombres if os.path.islink(os.path.join(carpeta, n))
                 and not os.path.exists(os.path.join(carpeta, n))]
        return rotos + (no_copiar if Path(carpeta) == fuente else [])
    # Los enlaces simbólicos se copian como archivos: FAT32 no los admite
    shutil.copytree(fuente, temporal, ignore=ignorar)
    if sistema == "linux":  # FAT32 decide el permiso de ejecución al crear el archivo: se crea con su nombre final
        shutil.copy2(fuente / "Colector", temporal / EXE_USB_LINUX)
    for p in anteriores:
        _borrar(p)
    if windows:
        for p in temporal.iterdir():
            p.rename(destino / p.name)
        temporal.rmdir()
    else:
        temporal.rename(destino / SUBCARPETA_LINUX)
    (destino / CARPETA_RESULTADOS).mkdir(exist_ok=True)  # los escaneos ya guardados se conservan
    if sistema == "linux":
        (destino / LANZADOR).write_bytes(SCRIPT_LINUX.encode("utf-8"))  # finales de línea de Unix
    (unidad / INSTRUCCIONES).write_text(_instrucciones(destino), encoding="utf-8-sig")
    return destino / PARA_EJECUTAR[sistema]


def preparar_varios(unidad, sistemas: list[str] | None = None) -> dict[str, Path]:
    """Prepara en la memoria los colectores de `sistemas` (por defecto, todos los que trae esta
    instalación). Devuelve {sistema: lo que hay que ejecutar}. Si falta espacio para todos, no copia
    ninguno."""
    sistemas = sistemas or disponibles()
    unidad = Path(unidad)
    if unidad.is_dir():
        destino = unidad / CARPETA
        necesario = sum(_tamano(origen(s)) - _tamano(origen(s) / CARPETA_RESULTADOS)
                        - sum(_tamano(p) for p in _PARTES[s](destino)) for s in sistemas)
        if necesario > shutil.disk_usage(unidad).free:
            raise OSError(f"No hay espacio suficiente en {unidad} para los colectores de "
                          f"{', '.join(NOMBRES[s] for s in sistemas)} "
                          f"(se necesitan {max(necesario, 0) / 1024 ** 2:.0f} MB).")
    return {s: preparar(unidad, sistema=s) for s in sistemas}
