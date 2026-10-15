# Colores de prioridad: (fondo, texto)
PRIORITY_COLORS = {
    "Alta": ("#fbe6e3", "#c0392b"),
    "Media": ("#fbf0d9", "#b7791f"),
    "Baja": ("#e1f3e8", "#2f855a"),
}
# Mismos tonos para los estados (el texto siempre va escrito, nunca solo el color)
STATUS_COLORS = {
    "Atención": PRIORITY_COLORS["Alta"],
    "Revisar": PRIORITY_COLORS["Media"],
    "Buen estado": PRIORITY_COLORS["Baja"],
    "Sin referencia": ("#eef1f4", "#5f6b77"),
}
NEUTRAL_COLORS = ("#eef1f4", "#5f6b77")
ACCENT = "#1f6f8b"
ACCENT_LIGHT = "#5ec1df"
MUTED = "#5f6b77"
TRACK = "#e6eaee"

QSS = """
QWidget { font-family: "Segoe UI"; font-size: 14px; }
QLabel { color: #1b2430; }
QMainWindow, QDialog { background: #eef1f4; }
QToolTip { background: #1d2733; color: white; border: none; padding: 4px 6px; }

#SidebarBox { background: #1d2733; }
#Sidebar { background: #1d2733; border: none; outline: 0; padding-top: 8px; }
#Sidebar::item { color: #a9b6c4; padding: 10px 14px; border-left: 3px solid transparent; }
#Sidebar::item:hover { color: white; }
#Sidebar::item:selected { background: #2a3644; color: white;
                          border-left: 3px solid #5ec1df; font-weight: 600; }
QPushButton#Logout { background: transparent; color: #a9b6c4; border: none;
                     border-top: 1px solid #2a3644; text-align: left; padding: 12px 17px; }
QPushButton#Logout:hover { color: white; background: #2a3644; }

#TopBar { background: white; border-bottom: 1px solid #d9dfe5; }
#AppName { font-weight: 600; font-size: 15px; }
#Chip { border: 1px solid #d9dfe5; border-radius: 4px; padding: 3px 9px;
        color: #5f6b77; font-size: 12px; }

QLineEdit, QPlainTextEdit, QTextEdit { background: white; border: 1px solid #d9dfe5;
            border-radius: 4px; padding: 8px; color: #1b2430; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #1f6f8b; }
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
QListWidget { background: white; border: 1px solid #d9dfe5; border-radius: 4px; color: #1b2430; }
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: #e1f0f5; color: #1b2430; }
QCompleter QAbstractItemView, QListView { background: white; color: #1b2430; }
QTreeWidget { background: white; color: #1b2430; }

QPushButton#Primary { background: #1f6f8b; color: white; border: none; font-weight: 600;
                      border-radius: 4px; padding: 9px 18px; min-height: 26px; }
QPushButton#Primary:hover { background: #185a72; }
QPushButton#Primary:disabled { background: #a9c7d2; }
QPushButton#Secondary { background: white; color: #1b2430; border: 1px solid #d9dfe5;
                        border-radius: 4px; padding: 8px 14px; }
QPushButton#Secondary:hover { border-color: #1f6f8b; }
QPushButton#Secondary:disabled { color: #a0a9b3; }
QPushButton#Link { background: transparent; border: none; color: #1f6f8b;
                   padding: 2px 0; text-align: left; font-weight: 600; }
QPushButton#Link:hover { text-decoration: underline; }
QPushButton#Link:disabled { color: #a0a9b3; }
QPushButton#ChipBtn { background: white; border: 1px solid #d9dfe5;
                      border-radius: 16px; padding: 6px 14px; color: #1b2430; }
QPushButton#ChipBtn:hover { border-color: #1f6f8b; }
QPushButton#ChipBtn:checked { background: #e1f0f5; border-color: #1f6f8b;
                              color: #1f6f8b; font-weight: 600; }

#LoginLeft { background: #1d2733; }
#LoginLeft QLabel { color: white; }
#LoginLeft QLabel#LoginMuted { color: #a9b6c4; }
#LoginCard { background: white; border: 1px solid #d9dfe5; border-radius: 6px; }

#Muted { color: #5f6b77; font-size: 12px; }
#Error { color: #c0392b; font-size: 13px; }
#Ok { color: #2f855a; font-size: 13px; font-weight: 600; }
#PageTitle { font-size: 20px; font-weight: 600; }
#SectionTitle { font-size: 15px; font-weight: 600; }
#Code { color: #1f6f8b; font-weight: 600; }
#BigNumber { font-size: 30px; font-weight: 600; }

#Panel { background: white; border: 1px solid #d9dfe5; border-radius: 6px; }
#Col { background: #e6eaee; border: 1px solid #d9dfe5; border-radius: 6px; }
#ColTitle { color: #5f6b77; font-size: 12px; font-weight: 600; }
#Counter { background: white; color: #5f6b77; border-radius: 9px; padding: 1px 8px;
           font-size: 12px; font-weight: 600; }
#Card { background: white; border: 1px solid #d9dfe5; border-radius: 4px; }
#Card:hover { border-color: #1f6f8b; }
#Alert { background: #fbf0d9; border: 1px solid #b7791f; border-radius: 4px; }
#Row { background: white; border: none; border-bottom: 1px solid #eef1f4; }

#RuleList { border: none; border-radius: 0; }
#RuleList::item { padding: 8px 10px; border-left: 3px solid transparent;
                  border-bottom: 1px solid #eef1f4; }
#RuleList::item:selected { background: #e1f0f5; color: #1b2430; border-left: 3px solid #1f6f8b; }

QTableWidget { background: white; border: 1px solid #d9dfe5; border-radius: 6px;
               gridline-color: #eef1f4; alternate-background-color: white; color: #1b2430; }
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #eef1f4; }
QTableWidget::item:selected { background: #e1f0f5; color: #1b2430; }
QHeaderView::section { background: #f6f8fa; color: #5f6b77; border: none;
                       border-bottom: 1px solid #d9dfe5; padding: 8px; font-size: 12px;
                       font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget#ScrollBody { background: transparent; }
"""
