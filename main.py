import sys
from PySide6.QtWidgets import QApplication
from app.ui.styles import QSS
from app.ui.login import LoginDialog
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    login = LoginDialog()
    if login.exec() != LoginDialog.Accepted:
        return 0
    win = MainWindow(login.user_id)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())