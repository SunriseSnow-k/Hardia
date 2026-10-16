"""Estilos de la interfaz. Los colores salen de la paleta activa (app/ui/tema.py)."""
from app.ui.tema import T, rellenar

# Colores de prioridad: (fondo, texto)
PRIORITY_COLORS = {
    "Alta": (T.peligro_suave, T.peligro),
    "Media": (T.aviso_suave, T.aviso),
    "Baja": (T.exito_suave, T.exito),
}
# Mismos tonos para los estados (el texto siempre va escrito, nunca solo el color)
STATUS_COLORS = {
    "Atención": PRIORITY_COLORS["Alta"],
    "Revisar": PRIORITY_COLORS["Media"],
    "Buen estado": PRIORITY_COLORS["Baja"],
    "Sin referencia": (T.fondo_app, T.texto_suave),
    # presupuesto
    "Enviado": (T.acento_suave, T.acento),
    "Aprobado": (T.exito_suave, T.exito),
    "Rechazado": (T.peligro_suave, T.peligro),
}
NEUTRAL_COLORS = (T.fondo_app, T.texto_suave)
ACCENT = T.acento
ACCENT_LIGHT = T.acento_claro
MUTED = T.texto_suave
TRACK = T.pista

QSS = rellenar("""
QWidget { font-family: "Segoe UI"; font-size: 14px; }
QLabel { color: $texto; }
QMainWindow, QDialog { background: $fondo_app; }
QToolTip { background: $lateral; color: $sobre_acento; border: none; padding: 4px 6px; }

#SidebarBox { background: $lateral; }
#Sidebar { background: $lateral; border: none; outline: 0; padding-top: 8px; }
#Sidebar::item { color: $lateral_texto; padding: 10px 14px; border-left: 3px solid transparent; }
#Sidebar::item:hover { color: $sobre_acento; }
#Sidebar::item:selected { background: $lateral_seleccion; color: $sobre_acento;
                          border-left: 3px solid $acento_claro; font-weight: 600; }
QPushButton#Logout { background: transparent; color: $lateral_texto; border: none;
                     border-top: 1px solid $lateral_seleccion; text-align: left; padding: 12px 17px; }
QPushButton#Logout:hover { color: $sobre_acento; background: $lateral_seleccion; }

#TopBar { background: $superficie; border-bottom: 1px solid $borde; }
#AppName { font-weight: 600; font-size: 15px; }
#Chip { border: 1px solid $borde; border-radius: 4px; padding: 3px 9px;
        color: $texto_suave; font-size: 12px; }

QLineEdit, QPlainTextEdit, QTextEdit { background: $superficie; border: 1px solid $borde;
            border-radius: 4px; padding: 8px; color: $texto; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: $acento; }
QComboBox { background: $superficie; border: 1px solid $borde; border-radius: 4px;
            padding: 7px 8px; color: $texto; }
QComboBox QAbstractItemView { background: $superficie; color: $texto;
                              selection-background-color: $acento_suave;
                              selection-color: $texto; }
QDateEdit { background: $superficie; border: 1px solid $borde; border-radius: 4px;
            padding: 6px 8px; color: $texto; }
QDateEdit:focus { border-color: $acento; }
QDateEdit:disabled { background: $fondo_app; color: $deshabilitado; }
QCalendarWidget QAbstractItemView { background: $superficie; color: $texto;
                                    selection-background-color: $acento;
                                    selection-color: $sobre_acento; }
QCheckBox { color: $texto; spacing: 6px; }
QListWidget { background: $superficie; border: 1px solid $borde; border-radius: 4px; color: $texto; }
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: $acento_suave; color: $texto; }
QCompleter QAbstractItemView, QListView { background: $superficie; color: $texto; }
QTreeWidget { background: $superficie; color: $texto; }

QPushButton#Primary { background: $acento; color: $sobre_acento; border: none; font-weight: 600;
                      border-radius: 4px; padding: 9px 18px; min-height: 26px; }
QPushButton#Primary:hover { background: $acento_hover; }
QPushButton#Primary:disabled { background: $acento_deshabilitado; }
QPushButton#Secondary { background: $superficie; color: $texto; border: 1px solid $borde;
                        border-radius: 4px; padding: 8px 14px; }
QPushButton#Secondary:hover { border-color: $acento; }
QPushButton#Secondary:disabled { color: $deshabilitado; }
QPushButton#Link { background: transparent; border: none; color: $acento;
                   padding: 2px 0; text-align: left; font-weight: 600; }
QPushButton#Link:hover { text-decoration: underline; }
QPushButton#Link:disabled { color: $deshabilitado; }
QPushButton#ChipBtn { background: $superficie; border: 1px solid $borde;
                      border-radius: 16px; padding: 6px 14px; color: $texto; }
QPushButton#ChipBtn:hover { border-color: $acento; }
QPushButton#ChipBtn:checked { background: $acento_suave; border-color: $acento;
                              color: $acento; font-weight: 600; }

#LoginLeft { background: $lateral; }
#LoginLeft QLabel { color: $sobre_acento; }
#LoginLeft QLabel#LoginMuted { color: $lateral_texto; }
#LoginCard { background: $superficie; border: 1px solid $borde; border-radius: 6px; }

#Muted { color: $texto_suave; font-size: 12px; }
#Error { color: $peligro; font-size: 13px; }
#Ok { color: $exito; font-size: 13px; font-weight: 600; }
#PageTitle { font-size: 20px; font-weight: 600; }
#SectionTitle { font-size: 15px; font-weight: 600; }
#Code { color: $acento; font-weight: 600; }
#BigNumber { font-size: 30px; font-weight: 600; }

#Panel { background: $superficie; border: 1px solid $borde; border-radius: 6px; }
#Col { background: $pista; border: 1px solid $borde; border-radius: 6px; }
#ColTitle { color: $texto_suave; font-size: 12px; font-weight: 600; }
#Counter { background: $superficie; color: $texto_suave; border-radius: 9px; padding: 1px 8px;
           font-size: 12px; font-weight: 600; }
#Card { background: $superficie; border: 1px solid $borde; border-radius: 4px; }
#Card:hover { border-color: $acento; }
#Alert { background: $aviso_suave; border: 1px solid $aviso; border-radius: 4px; }
#Row { background: $superficie; border: none; border-bottom: 1px solid $fondo_app; }

#RuleList { border: none; border-radius: 0; }
#RuleList::item { padding: 8px 10px; border-left: 3px solid transparent;
                  border-bottom: 1px solid $fondo_app; }
#RuleList::item:selected { background: $acento_suave; color: $texto; border-left: 3px solid $acento; }

QTableWidget { background: $superficie; border: 1px solid $borde; border-radius: 6px;
               gridline-color: $fondo_app; alternate-background-color: $superficie; color: $texto; }
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid $fondo_app; }
QTableWidget::item:selected { background: $acento_suave; color: $texto; }
QHeaderView::section { background: $fondo_cabecera; color: $texto_suave; border: none;
                       border-bottom: 1px solid $borde; padding: 8px; font-size: 12px;
                       font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget#ScrollBody { background: transparent; }
""")
