import ctypes
import logging
import multiprocessing
import sys

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from app import registro
from app.paths import data_dir, db_path, recurso
from app.version import APP_NAME, VERSION

log = logging.getLogger("app")
MUTEX = "SistemaDiagnosticoMutex"  # el instalador lo usa para pedir que se cierre el programa


def _instancia_unica() -> QLockFile | None:
    """Bloqueo que impide abrir el programa dos veces sobre la misma base de datos."""
    lock = QLockFile(str(data_dir() / "programa.lock"))
    lock.setStaleLockTime(0)  # solo se libera si el proceso que lo tomó ya no existe
    # Al reiniciar como administrador, la instancia anterior tarda un momento en cerrarse
    espera = 15000 if "--relanzado" in sys.argv else 0
    return lock if lock.tryLock(espera) else None


def _marcar_proceso():
    if sys.platform != "win32":
        return None
    try:  # ícono propio en la barra de tareas (y no el de Python)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SistemaDiagnostico.App")
    except Exception:
        pass
    try:
        return ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX)
    except Exception:
        return None


def _splash() -> QSplashScreen:
    pix = QPixmap(440, 220)
    pix.fill(QColor("#1d2733"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawPixmap(32, 62, QIcon(str(recurso("assets", "icono.png"))).pixmap(96, 96))
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 16, QFont.DemiBold))
    p.drawText(146, 100, APP_NAME)
    p.setPen(QColor("#a9b6c4"))
    p.setFont(QFont("Segoe UI", 10))
    p.drawText(146, 126, f"Versión {VERSION}")
    p.drawText(146, 150, "Cargando…")
    p.end()
    splash = QSplashScreen(pix)
    splash.show()
    return splash


def main() -> int:
    registro.configurar()
    mutex = _marcar_proceso()  # noqa: F841 (se mantiene mientras el programa esté abierto)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(str(recurso("assets", "icono.ico"))))
    try:  # el diseño es claro: no se usa el modo oscuro de Windows 11
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass

    lock = _instancia_unica()
    if lock is None:
        QMessageBox.information(None, APP_NAME, "El programa ya está abierto en este equipo.")
        return 0

    splash = _splash()
    app.processEvents()

    # Lo pesado se importa con la pantalla de carga ya visible
    from app.ai import paquete
    from app.db.database import Database
    from app.db.hardware_repo import HardwareRepository
    from app.db.repo import Repository
    from app.ui.login import LoginDialog
    from app.ui.main_window import MainWindow
    from app.ui.styles import QSS
    from app.ui.welcome import WelcomeDialog

    app.setStyleSheet(QSS)
    # La aplicación termina cuando se cierra la ventana principal sin pedir "Cerrar sesión";
    # cerrar el login no debe terminarla por su cuenta.
    app.setQuitOnLastWindowClosed(False)

    db = Database(db_path())
    repo = Repository(db)
    try:  # convierte los escaneos anteriores en capturas (no borra nada; se repite sin efecto)
        HardwareRepository(repo).migrate_legacy()
    except Exception:
        log.exception("Falló la migración de escaneos anteriores")  # no impide abrir el programa

    codigo = 0
    try:
        while True:
            login = LoginDialog(repo)
            if splash is not None:
                splash.finish(login)
                splash = None
            if login.exec() != LoginDialog.Accepted:
                break

            repo.session_tech = login.user_id  # autor de las notas y de los reportes de esta sesión
            log.info("Inicio de sesión: %s", login.user_id)

            if repo.get_setting("setup_done") != "1":
                WelcomeDialog(repo).exec()

            win = MainWindow(repo, login.user_id)
            win.closed.connect(app.quit)
            win.mostrar()
            codigo = app.exec()
            if not win.logout_requested:
                break
            repo.session_tech = ""
            win.deleteLater()
    finally:
        paquete.servidor.detener()
        db.close()
        lock.unlock()
        log.info("Cierre del programa")
    return codigo


if __name__ == "__main__":
    multiprocessing.freeze_support()  # la prueba de CPU usa procesos (necesario con PyInstaller)
    sys.exit(main())
