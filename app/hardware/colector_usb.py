"""Prepara una memoria USB con el colector portátil (Colector.exe).

El instalador trae el colector en la subcarpeta Colector del programa (build.ps1 lo genera con
PyInstaller y lo copia allí). Preparar el USB es copiar esa carpeta a <unidad>\\Colector junto
con un archivo de instrucciones. Los escaneos se guardan en <unidad>\\Colector\\Resultados, donde
la pantalla Escanear los busca; al actualizar el colector esa carpeta se conserva.
"""
import shutil
import sys
from pathlib import Path

from .diag_file import CARPETA_COLECTOR, CARPETA_RESULTADOS

CARPETA = CARPETA_COLECTOR
EXE = "Colector.exe"
INSTRUCCIONES = "LEAME - Colector.txt"
TEXTO_INSTRUCCIONES = """COLECTOR DE DIAGNÓSTICO

En el PC del cliente:
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


def origen() -> Path:
    """Carpeta del colector que acompaña al programa: junto al ejecutable instalado o, en
    desarrollo, la que deja build.ps1 en dist\\Colector."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CARPETA
    return Path(__file__).resolve().parents[2] / "dist" / CARPETA


def disponible(carpeta: Path | None = None) -> bool:
    return ((carpeta or origen()) / EXE).is_file()


def _tamano(carpeta: Path) -> int:
    """Tamaño del programa, sin contar los escaneos de Resultados."""
    return sum(f.stat().st_size for f in carpeta.rglob("*")
               if f.is_file() and f.relative_to(carpeta).parts[0] != CARPETA_RESULTADOS)


def preparar(unidad, carpeta: Path | None = None) -> Path:
    """Copia el colector a <unidad>\\Colector (reemplaza una versión anterior, conservando los
    escaneos de Resultados) y deja las instrucciones en la raíz. Devuelve la ruta del Colector.exe."""
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
    return destino / EXE
