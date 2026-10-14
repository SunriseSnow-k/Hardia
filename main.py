import multiprocessing
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app.paths import db_path
from app.db.database import Database
from app.db.hardware_repo import HardwareRepository
from app.db.repo import Repository
from app.ui.styles import QSS
from app.ui.login import LoginDialog
from app.ui.main_window import MainWindow
from app.ui.welcome import WelcomeDialog


def main() -> int:
    app = QApplication(sys.argv)
    try:  # el diseño es claro: no se usa el modo oscuro de Windows 11
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass
    app.setStyleSheet(QSS)
    # La aplicación termina cuando se cierra la ventana principal sin pedir "Cerrar sesión";
    # cerrar el login no debe terminarla por su cuenta.
    app.setQuitOnLastWindowClosed(False)

    db = Database(db_path())
    repo = Repository(db)
    try:  # convierte los escaneos anteriores en capturas (no borra nada; se repite sin efecto)
        HardwareRepository(repo).migrate_legacy()
    except Exception:
        pass  # un fallo de migración no debe impedir abrir el programa

    codigo = 0
    while True:
        login = LoginDialog(repo)
        if login.exec() != LoginDialog.Accepted:
            break

        repo.session_tech = login.user_id  # autor de las notas y de los reportes de esta sesión

        if repo.get_setting("setup_done") != "1":
            WelcomeDialog(repo).exec()

        win = MainWindow(repo, login.user_id)
        win.closed.connect(app.quit)
        win.show()
        codigo = app.exec()
        if not win.logout_requested:
            break
        repo.session_tech = ""
        win.deleteLater()

    db.close()
    return codigo


if __name__ == "__main__":
    multiprocessing.freeze_support()  # la prueba de CPU usa procesos (necesario con PyInstaller)
    sys.exit(main())
