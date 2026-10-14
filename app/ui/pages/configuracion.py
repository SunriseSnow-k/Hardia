import shutil
import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)
from app import backup
from app.db.repo import Repository
from app.db.users_repo import UsersRepository
from app.hardware.diag_file import removable_drives
from app.health.references import PAQUETE, load_references, ruta_activa, ruta_taller
from app.paths import backups_dir, data_dir, reports_dir
from app.ui.widgets import (AreaDesplazable, cabecera, limpiar_layout, lista_dato_valor, muted, panel,
                            ruta_cortable)


def _abrir(ruta):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))


class ConfiguracionPage(QWidget):
    restored = Signal()

    def __init__(self, repo: Repository, user_id: str):
        super().__init__()
        self.repo = repo
        self.user_id = user_id
        self.ur = UsersRepository(repo)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        textos, _t, _s = cabecera("Configuración", "Datos del taller, técnicos, copias de seguridad y carpetas.")
        outer.addLayout(textos)

        inner = QWidget()
        inner.setObjectName("ScrollBody")
        lay = QGridLayout(inner)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(12)
        scroll = AreaDesplazable(inner)
        outer.addWidget(scroll, 1)

        # --- Taller ---
        p1, v1 = self._panel("Datos del taller")
        self.nombre = QLineEdit()
        self.telefono = QLineEdit()
        self._campo(v1, "Nombre del negocio", self.nombre)
        self._campo(v1, "Teléfono (opcional)", self.telefono)
        v1.addWidget(muted("Aparecen en la cabecera de los reportes PDF."))
        b = QPushButton("Guardar")
        b.setObjectName("Primary")
        b.clicked.connect(self._guardar_negocio)
        self.msg_neg = QLabel("")
        self.msg_neg.setWordWrap(True)
        v1.addWidget(b, alignment=Qt.AlignLeft)
        v1.addWidget(self.msg_neg)
        v1.addStretch()
        lay.addWidget(p1, 0, 0)

        # --- Técnicos ---
        p3, v3 = self._panel("Técnicos")
        self.lista = QListWidget()
        self.lista.setMaximumHeight(110)
        v3.addWidget(self.lista)
        self.nu_id = QLineEdit()
        self.nu_id.setPlaceholderText("ID del nuevo técnico (ej.: TEC-002)")
        self.nu_pw = QLineEdit()
        self.nu_pw.setPlaceholderText("Contraseña (mínimo 6 caracteres)")
        self.nu_pw.setEchoMode(QLineEdit.Password)
        b2 = QPushButton("Crear técnico")
        b2.setObjectName("Secondary")
        b2.clicked.connect(self._crear_tecnico)
        fila_nu = QHBoxLayout()
        fila_nu.addWidget(self.nu_id, 1)
        fila_nu.addWidget(self.nu_pw, 1)
        v3.addLayout(fila_nu)
        v3.addWidget(b2, alignment=Qt.AlignLeft)
        etiqueta = QLabel("Cambiar mi contraseña")
        etiqueta.setStyleSheet("font-weight:600;")
        v3.addWidget(etiqueta)
        self.pw_actual = QLineEdit()
        self.pw_actual.setPlaceholderText("Contraseña actual")
        self.pw_actual.setEchoMode(QLineEdit.Password)
        self.pw_nueva = QLineEdit()
        self.pw_nueva.setPlaceholderText("Nueva contraseña")
        self.pw_nueva.setEchoMode(QLineEdit.Password)
        b3 = QPushButton("Cambiar contraseña")
        b3.setObjectName("Secondary")
        b3.clicked.connect(self._cambiar_pw)
        fila_pw = QHBoxLayout()
        fila_pw.addWidget(self.pw_actual, 1)
        fila_pw.addWidget(self.pw_nueva, 1)
        v3.addLayout(fila_pw)
        v3.addWidget(b3, alignment=Qt.AlignLeft)
        self.msg_us = QLabel("")
        self.msg_us.setWordWrap(True)
        v3.addWidget(self.msg_us)
        v3.addStretch()
        lay.addWidget(p3, 0, 1)

        # --- Copias de seguridad ---
        p2, v2 = self._panel("Copias de seguridad")
        self.estado_bk = QLabel("")
        self.estado_bk.setWordWrap(True)
        self.estado_bk.setStyleSheet("font-weight:600;")
        tip = muted("Guarde también una copia en un USB o disco externo: protege sus datos "
                    "si este equipo falla.")
        self.chk_auto = QCheckBox("Crear una copia automática al cerrar el programa "
                                  "(se conservan las 10 más recientes)")
        self.chk_auto.toggled.connect(self._cambiar_auto)
        v2.addWidget(self.chk_auto)
        v2.addWidget(self.estado_bk)
        v2.addWidget(tip)
        f1 = QHBoxLayout()
        f2 = QHBoxLayout()
        for fila, textos_b in ((f1, [("Crear copia ahora", "Secondary", self._crear_copia),
                                     ("Guardar copia en otra ubicación…", "Secondary", self._copia_en)]),
                               (f2, [("Restaurar copia…", "Secondary", self._restaurar),
                                     ("Abrir carpeta de copias", "Secondary",
                                      lambda: _abrir(backups_dir()))])):
            for texto, nombre, fn in textos_b:
                btn = QPushButton(texto)
                btn.setObjectName(nombre)
                btn.clicked.connect(fn)
                fila.addWidget(btn)
            fila.addStretch()
            v2.addLayout(fila)
        self.msg_bk = QLabel("")
        self.msg_bk.setWordWrap(True)
        v2.addWidget(self.msg_bk)
        v2.addStretch()
        lay.addWidget(p2, 1, 0)

        # --- Carpetas ---
        p4, v4 = self._panel("Carpetas")
        v4.addWidget(lista_dato_valor([("Datos", ruta_cortable(data_dir())), ("Reportes", ruta_cortable(reports_dir())),
                                       ("Copias", ruta_cortable(backups_dir()))]))
        f3 = QHBoxLayout()
        for texto, ruta in (("Abrir carpeta de datos", data_dir), ("Abrir carpeta de reportes", reports_dir)):
            btn = QPushButton(texto)
            btn.setObjectName("Secondary")
            btn.clicked.connect(lambda _=False, r=ruta: _abrir(r()))
            f3.addWidget(btn)
        f3.addStretch()
        v4.addLayout(f3)
        v4.addStretch()
        lay.addWidget(p4, 1, 1)

        # --- Referencias de fábrica ---
        p5, v5 = self._panel("Referencias de fábrica")
        v5.addWidget(muted("Valores de fábrica que usa la pantalla Salud del equipo. Solo contiene datos "
                           "publicados o típicos documentados, cada uno con su fuente; lo que no está aquí "
                           "aparece como «Sin referencia»."))
        self.refs_box = QVBoxLayout()
        v5.addLayout(self.refs_box)
        f5 = QHBoxLayout()
        self.b_copia_refs = QPushButton("Crear copia editable del taller")
        self.b_copia_refs.setObjectName("Secondary")
        self.b_copia_refs.setToolTip("Copia la base a la carpeta de datos para que el taller pueda ampliarla")
        self.b_copia_refs.clicked.connect(self._copiar_referencias)
        b_abrir_refs = QPushButton("Abrir carpeta de la base")
        b_abrir_refs.setObjectName("Secondary")
        b_abrir_refs.clicked.connect(lambda: _abrir(ruta_activa().parent))
        f5.addWidget(self.b_copia_refs)
        f5.addWidget(b_abrir_refs)
        f5.addStretch()
        v5.addLayout(f5)
        self.msg_refs = QLabel("")
        self.msg_refs.setWordWrap(True)
        v5.addWidget(self.msg_refs)
        lay.addWidget(p5, 2, 0, 1, 2)
        lay.setColumnStretch(0, 1)
        lay.setColumnStretch(1, 1)
        lay.setRowStretch(3, 1)
        self.refresh()

    # ---------- utilidades ----------
    @staticmethod
    def _panel(titulo: str):
        return panel(titulo)

    @staticmethod
    def _campo(layout, etiqueta: str, widget: QWidget):
        l = QLabel(etiqueta)
        l.setObjectName("Muted")
        layout.addWidget(l)
        layout.addWidget(widget)

    @staticmethod
    def _set(lbl: QLabel, texto: str, ok: bool = True):
        lbl.setStyleSheet("color:#2f855a;font-weight:600;" if ok else "color:#c0392b;")
        lbl.setText(texto)

    def refresh(self):
        self.nombre.setText(self.repo.get_setting("business_name", ""))
        self.telefono.setText(self.repo.get_setting("business_phone", ""))
        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(self.repo.get_setting("auto_backup", "1") == "1")
        self.chk_auto.blockSignals(False)
        self._estado_copia()
        self._listar_usuarios()
        self._mostrar_referencias()

    def _estado_copia(self):
        ultima = backup.last_backup_time()
        n = len(backup.list_backups())
        if ultima:
            self.estado_bk.setText(f"Última copia: {ultima:%d/%m/%Y %H:%M} · {n} copia(s) guardada(s)")
        else:
            self.estado_bk.setText("Aún no hay copias de seguridad. Cree una ahora.")

    def _listar_usuarios(self):
        self.lista.clear()
        for u in self.ur.list_users():
            marca = "  (usted)" if u["tech_id"] == self.user_id else ""
            self.lista.addItem(f'{u["tech_id"]} · alta {u["created_at"][:10]}{marca}')

    # ---------- negocio ----------
    def _guardar_negocio(self):
        nombre = self.nombre.text().strip()
        if not nombre:
            self._set(self.msg_neg, "Escriba el nombre del negocio.", ok=False)
            return
        self.repo.set_setting("business_name", nombre)
        self.repo.set_setting("business_phone", self.telefono.text().strip())
        self._set(self.msg_neg, "Datos guardados.")

    # ---------- copias ----------
    def _cambiar_auto(self, activo: bool):
        self.repo.set_setting("auto_backup", "1" if activo else "0")

    def _crear_copia(self):
        try:
            ruta = backup.create_backup(self.repo.c)
        except (OSError, ValueError, sqlite3.Error) as e:
            self._set(self.msg_bk, f"No se pudo crear la copia: {e}", ok=False)
            return
        self._set(self.msg_bk, f"Copia creada: {ruta}")
        self._estado_copia()

    def _copia_en(self):
        unidades = removable_drives()
        base = unidades[0] if unidades else backups_dir()
        sugerido = str(base / f"{backup.MANUAL_PREFIX}{datetime.now():%Y%m%d-%H%M%S}.db")
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar copia de seguridad", sugerido,
                                              "Copia de seguridad (*.db)")
        if not ruta:
            return
        try:
            backup.backup_to(self.repo.c, ruta)
        except (OSError, ValueError, sqlite3.Error) as e:
            self._set(self.msg_bk, f"No se pudo guardar la copia: {e}", ok=False)
            return
        self._set(self.msg_bk, f"Copia guardada en {ruta}")

    def _restaurar(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar copia de seguridad",
                                              str(backups_dir()), "Copia de seguridad (*.db)")
        if not ruta:
            return
        try:
            backup.validate_backup(ruta)
        except ValueError as e:
            self._set(self.msg_bk, str(e), ok=False)
            return
        caja = QMessageBox(
            QMessageBox.Warning, "Restaurar copia",
            "Se reemplazarán TODOS los datos actuales (clientes, equipos, casos y técnicos) "
            "por los de la copia seleccionada.\n\n"
            "Antes se guardará una copia de los datos actuales.\n"
            "El programa se cerrará para aplicar los cambios.\n\n¿Desea continuar?",
            QMessageBox.NoButton, self)
        si = caja.addButton("Restaurar", QMessageBox.AcceptRole)
        no = caja.addButton("Cancelar", QMessageBox.RejectRole)
        caja.setDefaultButton(no)
        caja.exec()
        if caja.clickedButton() is not si:
            return
        try:
            seguridad = backup.restore_backup(self.repo.c, ruta)
        except (OSError, ValueError, sqlite3.Error) as e:
            self._set(self.msg_bk, f"No se pudo restaurar: {e}", ok=False)
            return
        QMessageBox.information(
            self, "Restauración completada",
            "Los datos se restauraron correctamente.\n\n"
            f"Se guardó una copia de los datos anteriores en:\n{seguridad}\n\n"
            "El programa se cerrará. Ábralo de nuevo para continuar.")
        self.restored.emit()

    # ---------- referencias de fábrica ----------
    def _mostrar_referencias(self):
        limpiar_layout(self.refs_box)
        try:
            refs = load_references()
        except ValueError as e:
            self.refs_box.addWidget(QLabel(str(e)))
            return
        taller = ruta_activa() != PAQUETE
        fuentes = sorted({r.get("fuente", "") for r in refs["cpus"] + refs["discos_por_tipo"] if r.get("fuente")})
        filas = [
            ("Base en uso", ("Copia del taller · " if taller else "Incluida en el programa · ")
             + ruta_cortable(refs["_ruta"])),
            ("Procesadores (límite térmico)", ", ".join(c.get("nombre", c.get("modelo", "?")) for c in refs["cpus"])
             or "Ninguno"),
            ("Tipos de disco", ", ".join(f'{d["tipo"]} ≈ {d["lectura_mb_s"]:.0f} MB/s'
                                         for d in refs["discos_por_tipo"]) or "Ninguno"),
            ("Puntajes de CPU del taller", str(len((refs.get("cpu_puntajes") or {}).get("modelos", [])))),
            ("Fuentes", " · ".join(fuentes) or "—"),
        ]
        self.refs_box.addWidget(lista_dato_valor(filas))
        self.b_copia_refs.setEnabled(not taller)

    def _copiar_referencias(self):
        destino = ruta_taller()
        if destino.exists():
            self._set(self.msg_refs, "La copia del taller ya existe.", ok=False)
            return
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PAQUETE, destino)
        except OSError as e:
            self._set(self.msg_refs, f"No se pudo crear la copia: {e}", ok=False)
            return
        self._set(self.msg_refs, f"Copia creada en {destino}. Las entradas nuevas deben indicar su fuente.")
        self._mostrar_referencias()

    # ---------- técnicos ----------
    def _crear_tecnico(self):
        tech_id = self.nu_id.text().strip().upper()
        try:
            self.repo.create_user(tech_id, self.nu_pw.text())
        except ValueError as e:
            self._set(self.msg_us, str(e), ok=False)
            return
        self.nu_id.clear()
        self.nu_pw.clear()
        self._set(self.msg_us, f"Técnico {tech_id} creado.")
        self._listar_usuarios()

    def _cambiar_pw(self):
        try:
            self.ur.change_password(self.user_id, self.pw_actual.text(), self.pw_nueva.text())
        except ValueError as e:
            self._set(self.msg_us, str(e), ok=False)
            return
        self.pw_actual.clear()
        self.pw_nueva.clear()
        self._set(self.msg_us, "Contraseña actualizada.")