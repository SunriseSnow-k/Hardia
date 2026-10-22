"""Diferencias entre sistemas operativos (Windows y Linux) en un solo lugar.

El resto del programa pregunta aquí en vez de mirar sys.platform por su cuenta.
"""
import ctypes
import os
import sys

ES_WINDOWS = sys.platform == "win32"
ES_LINUX = sys.platform.startswith("linux")
# Clave del sistema: la usa el colector USB (una carpeta por sistema)
SISTEMA = "windows" if ES_WINDOWS else "linux"

# Fuente de la interfaz: Segoe UI en Windows; en Linux, la sans-serif del escritorio (fontconfig)
FUENTE = "Segoe UI" if ES_WINDOWS else "Sans Serif"


def nombre_sistema() -> str:
    return "Windows" if ES_WINDOWS else "Linux" if ES_LINUX else sys.platform


def es_administrador() -> bool:
    """Administrador en Windows; root en Linux."""
    try:
        if sys.platform == "win32":  # comparación literal: mypy la entiende en los dos sistemas
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def ejecutable(nombre: str) -> str:
    """Nombre de un programa en este sistema: 'Colector' -> 'Colector.exe' en Windows."""
    return f"{nombre}.exe" if ES_WINDOWS else nombre
