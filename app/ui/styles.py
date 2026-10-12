# Colores de prioridad: (fondo, texto)
PRIORITY_COLORS = {
    "Alta": ("#fbe6e3", "#c0392b"),
    "Media": ("#fbf0d9", "#b7791f"),
    "Baja": ("#e1f3e8", "#2f855a"),
}

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
QComboBox { background: white; border: 1px solid #d9dfe5; border-radius: 4px;
            padding: 7px 8px; color: #1b2430; }
QComboBox QAbstractItemView { background: white; color: #1b2430;
                              selection-background-color: #e1f0f5;
                              selection-color: #1b2430; }
QDateEdit { background: white; border: 1px solid #d9dfe5; border-radius: 4px;
            padding: 6px 8px; color: #1b2430; }
QDateEdit:focus { border-color: #1f6f8b; }
QDateEdit:disabled { background: #eef1f4; color: #a0a9b3; }
QCalendarWidget QAbstractItemView { background: white; color: #1b2430;
                                    selection-background-color: #1f6f8b;
                                    selection-color: white; }
QCheckBox { color: #1b2430; spacing: 6px; }
QListWidget { background: white; border: 1px solid #d9dfe5; border-radius: 4px; }
QCompleter QAbstractItemView, QListView { background: white; color: #1b2430; }

QPushButton#Primary { background: #1f6f8b; color: white; border: none;
                      border-radius: 4px; padding: 9px 16px; }
QPushButton#Primary:hover { background: #185a72; }
QPushButton#Primary:disabled { background: #a9c7d2; }
QPushButton#Secondary { background: white; color: #1b2430; border: 1px solid #d9dfe5;
                        border-radius: 4px; padding: 8px 14px; }
QPushButton#Secondary:hover { border-color: #1f6f8b; }
QPushButton#Secondary:disabled { color: #a0a9b3; }
QPushButton#ChipBtn { background: white; border: 1px solid #d9dfe5;
                      border-radius: 12px; padding: 4px 12px; color: #1b2430; }
QPushButton#ChipBtn:checked { background: #e1f0f5; border-color: #1f6f8b;
                              color: #1f6f8b; font-weight: 600; }

#LoginLeft { background: #1d2733; }
#LoginLeft QLabel { color: white; }
#LoginIcon { border: 2px solid #5ec1df; border-radius: 8px; color: #5ec1df;
             font-family: Consolas; font-size: 22px; padding: 22px 26px; }

#Muted { color: #66727f; font-size: 12px; }
#Error { color: #c0392b; font-size: 13px; }
#Ok { color: #2f855a; font-size: 13px; font-weight: 600; }
#PageTitle { font-size: 20px; font-weight: 600; }
#SectionTitle { font-size: 15px; font-weight: 600; }

#Panel { background: white; border: 1px solid #d9dfe5; border-radius: 6px; }
#Col { background: #e6eaee; border: 1px solid #d9dfe5; border-radius: 6px; }
#ColTitle { color: #66727f; font-size: 12px; font-weight: 600; }
#Card { background: white; border: 1px solid #d9dfe5; border-radius: 4px; }
#Card:hover { border-color: #1f6f8b; }
#Alert { background: #fbf0d9; border: 1px solid #b7791f; border-radius: 4px; }

QTableWidget { background: white; border: 1px solid #d9dfe5; border-radius: 4px;
               gridline-color: #eef1f4; alternate-background-color: #f8fafb; }
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: #e1f0f5; color: #1b2430; }
QHeaderView::section { background: #f6f8fa; color: #66727f; border: none;
                       border-bottom: 1px solid #d9dfe5; padding: 8px; font-size: 12px; }
QScrollArea { border: none; background: transparent; }
"""