import sys
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
    app.setStyleSheet(QSS)

    db = Database(db_path())
    repo = Repository(db)
    try:  # convierte los escaneos anteriores en capturas (no borra nada; se repite sin efecto)
        HardwareRepository(repo).migrate_legacy()
    except Exception:
        pass  # un fallo de migración no debe impedir abrir el programa

    login = LoginDialog(repo)
    if login.exec() != LoginDialog.Accepted:
        db.close()
        return 0

    if repo.get_setting("setup_done") != "1":
        WelcomeDialog(repo).exec()

    win = MainWindow(repo, login.user_id)
    win.show()
    codigo = app.exec()
    db.close()
    return codigo


if __name__ == "__main__":
    sys.exit(main())