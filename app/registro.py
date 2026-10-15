"""Registro de eventos y errores en %APPDATA%\\SistemaDiagnostico\\Registros.

Los errores no controlados quedan en el registro y se muestran en un aviso con los detalles
para copiarlos, en lugar de cerrar el programa sin explicación."""
import contextlib
import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.paths import data_dir
from app.version import APP_NAME, VERSION

log = logging.getLogger("app")


def carpeta() -> Path:
    path = data_dir() / "Registros"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archivo() -> Path:
    return carpeta() / "diagnostico.log"


def configurar() -> Path:
    """Activa el registro rotativo (5 archivos de 1 MB) y los avisos de error. Devuelve la ruta."""
    raiz = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in raiz.handlers):
        h = RotatingFileHandler(archivo(), maxBytes=1024 * 1024, backupCount=4, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        raiz.addHandler(h)
        raiz.setLevel(logging.INFO)
    sys.excepthook = _excepthook
    threading.excepthook = lambda a: _excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    log.info("Inicio de %s %s (Python %s, %s)", APP_NAME, VERSION, sys.version.split()[0],
             "empaquetado" if getattr(sys, "frozen", False) else "desarrollo")
    return archivo()


def _excepthook(tipo, valor, tb):
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, tb)
        return
    log.critical("Error no controlado", exc_info=(tipo, valor, tb))
    with contextlib.suppress(Exception):  # el aviso nunca debe provocar otro error
        _avisar("".join(traceback.format_exception(tipo, valor, tb)), f"{tipo.__name__}: {valor}")


def _avisar(detalle: str, resumen: str):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        return  # fuera del hilo de la interfaz solo se registra
    caja = QMessageBox()
    caja.setIcon(QMessageBox.Icon.Warning)
    caja.setWindowTitle("Ocurrió un error")
    caja.setText("Ocurrió un error inesperado. El programa puede seguir funcionando; si el problema "
                 "se repite, envíe al soporte el archivo de registro:")
    caja.setInformativeText(f"{archivo()}\n\n{resumen}")
    caja.setDetailedText(f"{APP_NAME} {VERSION}\n\n{detalle}")
    caja.exec()
