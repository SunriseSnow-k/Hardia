import os
import sys

import pytest

# Las pruebas de interfaz se ejecutan sin abrir ventanas reales.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _sin_abrir_archivos(monkeypatch):
    """Las pruebas nunca abren visores (PDF, carpetas) en el escritorio del usuario."""
    from PySide6.QtGui import QDesktopServices
    abiertos = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: abiertos.append(url) or True))
    return abiertos


def pytest_sessionfinish(session, exitstatus):
    session.config._codigo_salida = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """Las pruebas dejan muchas ventanas de Qt creadas. Si Python las destruye al salir, el orden de
    destrucción de PySide6 puede abortar el proceso y pytest devolvería un error aunque todo haya
    pasado (build.ps1 no generaría el instalador). Con el resumen ya impreso, se termina el proceso
    con el código real de las pruebas. En Windows se usa TerminateProcess: os._exit también descarga
    las DLL (Qt, .NET de LibreHardwareMonitor) y puede quedarse colgado."""
    codigo = getattr(config, "_codigo_salida", None)
    if codigo is None or "PySide6.QtWidgets" not in sys.modules:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.TerminateProcess(k32.GetCurrentProcess(), codigo)
    os._exit(codigo)
