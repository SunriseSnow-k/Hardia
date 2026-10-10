QSS = """
QWidget { font-family: "Segoe UI"; font-size: 14px; }
QLabel { color: #1b2430; }
QMainWindow, QDialog { background: #eef1f4; }

#Sidebar { background: #1d2733; border: none; outline: 0; padding-top: 8px; }
#Sidebar::item { color: #a9b6c4; padding: 10px 14px; border-left: 3px solid transparent; }
#Sidebar::item:hover { color: white; }
#Sidebar::item:selected { background: #2a3644; color: white;
                          border-left: 3px solid #5ec1df; font-weight: 600; }

#TopBar { background: white; border-bottom: 1px solid #d9dfe5; }
#Chip { border: 1px solid #d9dfe5; border-radius: 4px; padding: 3px 9px;
        color: #66727f; font-size: 12px; }

QLineEdit { background: white; border: 1px solid #d9dfe5; border-radius: 4px;
            padding: 8px; color: #1b2430; }
QLineEdit:focus { border-color: #1f6f8b; }

QPushButton#Primary { background: #1f6f8b; color: white; border: none;
                      border-radius: 4px; padding: 9px 16px; }
QPushButton#Primary:hover { background: #185a72; }

#LoginLeft { background: #1d2733; }
#LoginLeft QLabel { color: white; }
#LoginIcon { border: 2px solid #5ec1df; border-radius: 8px; color: #5ec1df;
             font-family: Consolas; font-size: 22px; padding: 22px 26px; }
#Muted { color: #66727f; font-size: 12px; }
#Error { color: #c0392b; font-size: 13px; }
#PageTitle { font-size: 20px; font-weight: 600; }
"""