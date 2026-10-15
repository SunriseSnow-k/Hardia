import html
import logging
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ai import config as ia_config
from app.ai import paquete, prompts
from app.ai.ollama_client import TIMEOUT_RESPUESTA, OllamaError, has_model, list_models
from app.db.repo import Repository
from app.diagnosis.engine import load_rules
from app.ui.ai_widgets import AiStreamPanel
from app.ui.widgets import AreaDesplazable, cabecera, campo, muted, panel

log = logging.getLogger(__name__)

PUEDE = (
    "Lee los datos del taller que se le entregan: el caso, el diagnóstico por reglas y la base "
    "de conocimiento.",
    "Redacta resúmenes, explicaciones y mensajes para el cliente.",
    "Funciona en este equipo, sin Internet.",
)
NO_PUEDE = (
    "No modifica nada: no guarda, no borra ni cambia casos por su cuenta.",
    "No decide el diagnóstico: la validación final siempre es del técnico.",
    "Solo usa los datos que se le entregan; puede equivocarse, así que revise siempre su texto.",
    "Sin el paquete de IA, el programa sigue funcionando en modo reglas.",
)
MOTOR_TEXTO = {"paquete": "Paquete de IA integrado", "ollama": "Ollama (avanzado)"}
VERDE, AMBAR, ROJO, GRIS = "#2f855a", "#b7791f", "#c0392b", "#5f6b77"


def _lista(puntos, signo: str, color: str) -> QLabel:
    lbl = QLabel("<br>".join(f"<span style='color:{color};font-weight:600'>{signo}</span>&nbsp; "
                             f"{html.escape(p)}" for p in puntos))
    lbl.setTextFormat(Qt.RichText)
    lbl.setWordWrap(True)
    return lbl


class DescargaWorker(QThread):
    """Instala el motor (si falta) y un modelo del paquete, en segundo plano."""
    progreso = Signal(str, float)  # (texto, fracción 0..1)
    terminado = Signal(bool, str)  # (ok, mensaje)

    def __init__(self, modelo_id: str):
        super().__init__()
        self.modelo_id = modelo_id
        self._cancel = False
        self._ultimo = 0.0

    def cancel(self):
        self._cancel = True

    def _emitir(self, titulo: str, hecho: int, total: int):
        ahora = time.monotonic()
        if hecho < total and ahora - self._ultimo < 0.2:
            return
        self._ultimo = ahora
        if hecho >= total:
            self.progreso.emit(f"{titulo}: verificando el archivo…", 1.0)
        else:
            self.progreso.emit(f"{titulo}: {paquete.tamano_texto(hecho)} de {paquete.tamano_texto(total)}",
                               hecho / total)

    def run(self):
        cancelado = lambda: self._cancel  # noqa: E731
        try:
            if not paquete.motor_instalado():
                paquete.instalar_motor(lambda h, t: self._emitir("Motor de IA", h, t), cancelado)
            nombre = paquete.MODELOS[self.modelo_id]["nombre"]
            paquete.instalar_modelo(self.modelo_id, lambda h, t: self._emitir(nombre, h, t), cancelado)
            self.terminado.emit(True, f"{nombre} instalado. La IA ya funciona sin Internet.")
        except paquete.Cancelado:
            self.terminado.emit(False, "Descarga pausada. Pulse «Descargar» para continuar donde quedó.")
        except paquete.PaqueteError as e:
            self.terminado.emit(False, str(e))
        except Exception as e:  # imprevisto: se registra y se informa, no cierra el programa
            log.exception("Fallo al instalar el paquete de IA")
            self.terminado.emit(False, f"Error inesperado: {e}")


class FilaModelo(QFrame):
    """Un modelo del catálogo con su estado y su botón de descargar o eliminar."""
    descargar = Signal(str)
    eliminar = Signal(str)

    def __init__(self, modelo_id: str):
        super().__init__()
        self.modelo_id = modelo_id
        m = paquete.MODELOS[modelo_id]
        self.setStyleSheet("FilaModelo{border:1px solid #d9dfe5;border-radius:6px;}")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(f"<b>{html.escape(m['nombre'])}</b>")
        textos.addWidget(titulo)
        textos.addWidget(muted(m["descripcion"]))
        self.detalle = muted("")
        textos.addWidget(self.detalle)
        h.addLayout(textos, 1)
        self.estado = QLabel("")
        h.addWidget(self.estado, 0, Qt.AlignVCenter)
        self.boton = QPushButton("")
        self.boton.setCursor(Qt.PointingHandCursor)
        self.boton.clicked.connect(self._pulsado)
        h.addWidget(self.boton, 0, Qt.AlignVCenter)

    def actualizar(self, ocupado: bool):
        m = paquete.MODELOS[self.modelo_id]
        listo = paquete.instalado(self.modelo_id)
        ram = paquete.ram_gb()
        aviso = ""
        if ram and ram < m["ram_gb"] * 0.85:  # Windows informa algo menos que la RAM nominal
            aviso = (f" · <span style='color:{AMBAR}'>este equipo tiene {ram:.0f} GB de RAM: "
                     "puede ir lento</span>")
        self.detalle.setTextFormat(Qt.RichText)
        self.detalle.setText(f"Descarga de {paquete.tamano_texto(m['tamano'])} · licencia "
                             f"{m['licencia']}{aviso}")
        self.estado.setText(f"<b style='color:{VERDE}'>● Instalado</b>" if listo
                            else f"<span style='color:{GRIS}'>No instalado</span>")
        self.boton.setText("Eliminar" if listo else "Descargar")
        self.boton.setObjectName("Secondary" if listo else "Primary")
        self.boton.style().unpolish(self.boton)
        self.boton.style().polish(self.boton)
        self.boton.setEnabled(not ocupado)
        self._listo = listo

    def _pulsado(self):
        (self.eliminar if self._listo else self.descargar).emit(self.modelo_id)


class IaLocalPage(QWidget):
    settings_changed = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.descarga: DescargaWorker | None = None
        self._ollama: list[str] | None = None  # modelos de Ollama (None: no disponible)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        textos, _t, _s = cabecera("IA local",
                                  "Asistente opcional que funciona en este equipo, sin Internet. "
                                  "Nunca decide el diagnóstico: solo redacta y resume.")
        outer.addLayout(textos)

        inner = QWidget()
        inner.setObjectName("ScrollBody")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)
        scroll = AreaDesplazable(inner)
        outer.addWidget(scroll, 1)

        # --- Paquete de IA ---
        pp, vp = panel("Paquete de IA")
        vp.addWidget(muted("Elija un modelo y pulse «Descargar». Se descarga una sola vez (necesita "
                           "Internet solo en ese momento); después la IA funciona sin conexión. "
                           "Si la descarga se interrumpe, continúa donde quedó."))
        self.filas: list[FilaModelo] = []
        for modelo_id in paquete.MODELOS:
            fila = FilaModelo(modelo_id)
            fila.descargar.connect(self._descargar)
            fila.eliminar.connect(self._eliminar)
            self.filas.append(fila)
            vp.addWidget(fila)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(8)
        self.barra.setStyleSheet(
            "QProgressBar{background:#e6eaee;border:none;border-radius:4px;}"
            "QProgressBar::chunk{background:#1f6f8b;border-radius:4px;}")
        fila_p = QHBoxLayout()
        self.lbl_descarga = muted("")
        self.b_cancelar = QPushButton("Pausar")
        self.b_cancelar.setObjectName("Secondary")
        self.b_cancelar.clicked.connect(self._cancelar_descarga)
        fila_p.addWidget(self.lbl_descarga, 1)
        fila_p.addWidget(self.b_cancelar)
        vp.addWidget(self.barra)
        vp.addLayout(fila_p)
        self.msg_paquete = QLabel("")
        self.msg_paquete.setWordWrap(True)
        vp.addWidget(self.msg_paquete)
        self.b_quitar_todo = QPushButton("Eliminar el paquete completo (motor y modelos)")
        self.b_quitar_todo.setObjectName("Link")
        self.b_quitar_todo.setCursor(Qt.PointingHandCursor)
        self.b_quitar_todo.clicked.connect(self._quitar_todo)
        vp.addWidget(self.b_quitar_todo, 0, Qt.AlignLeft)
        self._mostrar_progreso(False)
        lay.addWidget(pp)

        arriba = QGridLayout()
        arriba.setHorizontalSpacing(12)

        # --- Estado y configuración ---
        p1, v1 = panel("Configuración")
        self.estado = QLabel("")
        self.estado.setTextFormat(Qt.RichText)
        self.estado.setWordWrap(True)
        v1.addWidget(self.estado)
        self.chk = QCheckBox("Activar IA local")
        self.cb_motor = QComboBox()
        for clave, texto in MOTOR_TEXTO.items():
            self.cb_motor.addItem(texto, clave)
        self.cb_motor.currentIndexChanged.connect(self._cambio_motor)
        self.cb_modelo = QComboBox()
        self.cb_modo = QComboBox()
        self.cb_modo.addItem("Rápido (solo reglas; la IA se pide con un botón)", "rapido")
        self.cb_modo.addItem("Completo (reglas + análisis automático de IA)", "completo")
        v1.addWidget(self.chk)
        fila_c = QHBoxLayout()
        fila_c.addWidget(campo("Motor", self.cb_motor), 1)
        fila_c.addWidget(campo("Modelo", self.cb_modelo), 2)
        v1.addLayout(fila_c)
        v1.addWidget(campo("Modo de diagnóstico", self.cb_modo))
        v1.addWidget(muted(f"Tiempo máximo de espera de una respuesta: {TIMEOUT_RESPUESTA} s "
                           "(valor fijo del programa)."))
        fila = QHBoxLayout()
        b_save = QPushButton("Guardar")
        b_save.setObjectName("Primary")
        b_save.clicked.connect(self._guardar)
        b_test = QPushButton("Probar")
        b_test.setObjectName("Secondary")
        b_test.setToolTip("Envía una consulta corta al modelo y mide cuánto tarda")
        b_test.clicked.connect(self._probar)
        b_chk = QPushButton("Comprobar de nuevo")
        b_chk.setObjectName("Secondary")
        b_chk.clicked.connect(self.refresh)
        fila.addWidget(b_save)
        fila.addWidget(b_test)
        fila.addWidget(b_chk)
        fila.addStretch()
        v1.addLayout(fila)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v1.addWidget(self.msg)
        self.test_panel = AiStreamPanel(altura=50, msg_cancel="Prueba cancelada.")
        v1.addWidget(self.test_panel)
        arriba.addWidget(p1, 0, 0)

        # --- Qué puede y qué no ---
        p2, v2 = panel("Qué puede y qué no")
        v2.addWidget(_lista(PUEDE, "✓", VERDE))
        v2.addSpacing(6)
        v2.addWidget(_lista(NO_PUEDE, "✕", ROJO))
        v2.addStretch()
        arriba.addWidget(p2, 0, 1)
        arriba.setColumnStretch(0, 3)
        arriba.setColumnStretch(1, 2)
        lay.addLayout(arriba)

        # --- Soporte ---
        p3, v3 = panel("Consultar soporte")
        v3.addWidget(muted("Pregunte sobre un problema; la respuesta se apoya en la base de "
                           "conocimiento local."))
        self.pregunta = QLineEdit()
        self.pregunta.setPlaceholderText("Ej.: ¿Qué reviso si el equipo se calienta y el ventilador suena fuerte?")
        self.pregunta.returnPressed.connect(self._preguntar)
        b_ask = QPushButton("Preguntar")
        b_ask.setObjectName("Secondary")
        b_ask.clicked.connect(self._preguntar)
        fila_p = QHBoxLayout()
        fila_p.addWidget(self.pregunta, 1)
        fila_p.addWidget(b_ask)
        v3.addLayout(fila_p)
        self.soporte = AiStreamPanel(vacio="La respuesta aparecerá aquí.", altura=130,
                                     msg_cancel="Consulta cancelada.")
        v3.addWidget(self.soporte)
        lay.addWidget(p3)

        # --- Ayuda para Ollama ---
        p4, v4 = panel("Usar Ollama (avanzado)")
        txt = QLabel(
            "Si ya usa Ollama, puede elegirlo como motor en Configuración:<br>"
            "1. Instale Ollama desde ollama.com y déjelo en ejecución.<br>"
            "2. En una terminal: <b>ollama pull llama3.2:3b</b> (o <b>llama3.2:1b</b> si el equipo es modesto).<br>"
            "3. Elija el motor «Ollama (avanzado)» y pulse «Probar».")
        txt.setTextFormat(Qt.RichText)
        txt.setWordWrap(True)
        v4.addWidget(txt)
        lay.addWidget(p4)
        lay.addStretch()
        self.refresh()

    # ---------- utilidades ----------
    def _set_msg(self, texto: str, ok: bool = True):
        self.msg.setStyleSheet(f"color:{VERDE};font-weight:600;" if ok else f"color:{ROJO};")
        self.msg.setText(texto)

    def _set_msg_paquete(self, texto: str, ok: bool = True):
        self.msg_paquete.setStyleSheet(f"color:{VERDE};font-weight:600;" if ok else f"color:{ROJO};")
        self.msg_paquete.setText(texto)

    def _ocupado(self) -> bool:
        return self.descarga is not None and self.descarga.isRunning()

    def _mostrar_progreso(self, visible: bool):
        self.barra.setVisible(visible)
        self.lbl_descarga.setVisible(visible)
        self.b_cancelar.setVisible(visible)

    def _motor_elegido(self) -> str:
        return self.cb_motor.currentData() or "paquete"

    def _modelo_elegido(self) -> str:
        if self._motor_elegido() == "paquete":
            return self.cb_modelo.currentData() or ia_config.modelo_paquete_por_defecto()
        return self.cb_modelo.currentText().strip() or ia_config.DEFAULT_MODEL

    def _llenar_modelos(self, seleccion: str | None = None):
        motor = self._motor_elegido()
        anterior = seleccion or (self._modelo_elegido() if self.cb_modelo.count() else "")
        self.cb_modelo.blockSignals(True)
        self.cb_modelo.clear()
        if motor == "paquete":
            self.cb_modelo.setEditable(False)
            for modelo_id, m in paquete.MODELOS.items():
                sufijo = "" if paquete.modelo_instalado(modelo_id) else " (no descargado)"
                self.cb_modelo.addItem(m["nombre"] + sufijo, modelo_id)
            i = self.cb_modelo.findData(anterior)
            self.cb_modelo.setCurrentIndex(max(i, 0))
        else:
            self.cb_modelo.setEditable(True)
            nombres = []
            guardado = self.repo.get_setting("ia_model", ia_config.DEFAULT_MODEL) or ia_config.DEFAULT_MODEL
            for n in [guardado, *(self._ollama or []), *ia_config.MODELOS_SUGERIDOS]:
                if n not in nombres:
                    nombres.append(n)
            self.cb_modelo.addItems(nombres)
            self.cb_modelo.setCurrentText(anterior if anterior and anterior not in paquete.MODELOS
                                          else guardado)
        self.cb_modelo.blockSignals(False)

    def _cambio_motor(self, _i: int):
        if self._motor_elegido() == "ollama" and self._ollama is None:
            try:
                self._ollama = list_models()
            except OllamaError:
                self._ollama = None
        self._llenar_modelos()

    # ---------- estado ----------
    def refresh(self):
        cfg = ia_config.load(self.repo)
        try:
            self._ollama = list_models() if cfg["engine"] == "ollama" else None
        except OllamaError:
            self._ollama = None
        ocupado = self._ocupado()
        for fila in self.filas:
            fila.actualizar(ocupado)
        hay_algo = paquete.carpeta_motor().exists() or bool(paquete.modelos_instalados())
        self.b_quitar_todo.setVisible(hay_algo and not ocupado)

        self.cb_motor.blockSignals(True)
        self.cb_motor.setCurrentIndex(max(self.cb_motor.findData(cfg["engine"]), 0))
        self.cb_motor.blockSignals(False)
        self._llenar_modelos(cfg["model"])
        self.chk.setChecked(cfg["enabled"])
        self.cb_modo.setCurrentIndex(0 if cfg["mode"] == "rapido" else 1)

        m = html.escape(ia_config.nombre_modelo(cfg["model"]))
        if cfg["engine"] == "paquete":
            if paquete.instalado(cfg["model"]):
                self.estado.setText(f"<b style='color:{VERDE}'>● Paquete de IA listo · {m}.</b>")
            elif paquete.modelos_instalados() and paquete.motor_instalado():
                self.estado.setText(f"<b style='color:{AMBAR}'>● El modelo {m} no está descargado.</b> "
                                    "Descárguelo arriba o elija otro modelo.")
            else:
                self.estado.setText(f"<b style='color:{GRIS}'>● Paquete de IA no instalado.</b> "
                                    "Descargue un modelo arriba. Mientras tanto el sistema trabaja "
                                    "solo con reglas.")
        elif self._ollama is None:
            self.estado.setText(
                f"<b style='color:{ROJO}'>● Ollama no disponible.</b> Instálelo desde ollama.com y "
                "déjelo en ejecución, o use el paquete de IA integrado.")
        elif not has_model(self._ollama, cfg["model"]):
            self.estado.setText(
                f"<b style='color:{AMBAR}'>● Ollama disponible.</b> El modelo <b>{m}</b> no está instalado. "
                f"En una terminal ejecute: <b>ollama pull {m}</b>")
        else:
            lista = html.escape(", ".join(self._ollama))
            self.estado.setText(
                f"<b style='color:{VERDE}'>● Ollama disponible · modelo {m} listo.</b><br>"
                f"<span style='color:{GRIS}'>Modelos instalados: {lista}</span>")

    # ---------- paquete ----------
    def _descargar(self, modelo_id: str):
        if self._ocupado():
            return
        self._set_msg_paquete("")
        w = DescargaWorker(modelo_id)
        w.progreso.connect(self._progreso)
        w.terminado.connect(self._fin_descarga)
        self.descarga = w
        self.barra.setValue(0)
        self.lbl_descarga.setText("Conectando…")
        self.b_cancelar.setEnabled(True)
        self._mostrar_progreso(True)
        w.start()
        self.refresh()

    def _progreso(self, texto: str, fraccion: float):
        self.lbl_descarga.setText(texto)
        self.barra.setValue(int(fraccion * 1000))

    def _cancelar_descarga(self):
        if self.descarga is not None:
            self.descarga.cancel()
            self.b_cancelar.setEnabled(False)
            self.lbl_descarga.setText("Pausando…")

    def _fin_descarga(self, ok: bool, mensaje: str):
        modelo_id = self.descarga.modelo_id if self.descarga else ""
        if self.descarga is not None:
            self.descarga.wait()
        self.descarga = None
        self._mostrar_progreso(False)
        self._set_msg_paquete(mensaje, ok)
        if ok and not ia_config.check_ai(self.repo)[0]:
            # lo configurado no funciona: se pasa a usar lo que se acaba de instalar
            cfg = ia_config.load(self.repo)
            ia_config.save(self.repo, True, modelo_id, cfg["mode"], engine="paquete")
            self.settings_changed.emit()
        self.refresh()

    def _eliminar(self, modelo_id: str):
        nombre = paquete.MODELOS[modelo_id]["nombre"]
        if QMessageBox.question(self, "Eliminar modelo",
                                f"¿Eliminar {nombre} de este equipo? Podrá descargarlo de nuevo "
                                "cuando quiera.") != QMessageBox.Yes:
            return
        self.test_panel.shutdown()
        self.soporte.shutdown()
        try:
            paquete.eliminar_modelo(modelo_id)
        except OSError as e:
            self._set_msg_paquete(f"No se pudo eliminar: {e}", ok=False)
            return
        self._set_msg_paquete(f"{nombre} eliminado.")
        self.settings_changed.emit()
        self.refresh()

    def _quitar_todo(self):
        if QMessageBox.question(self, "Eliminar el paquete de IA",
                                "¿Eliminar el motor y todos los modelos de IA de este equipo? "
                                "El programa seguirá funcionando con reglas.") != QMessageBox.Yes:
            return
        self.test_panel.shutdown()
        self.soporte.shutdown()
        try:
            paquete.desinstalar()
        except OSError as e:
            self._set_msg_paquete(f"No se pudo eliminar: {e}", ok=False)
            return
        self._set_msg_paquete("Paquete de IA eliminado.")
        self.settings_changed.emit()
        self.refresh()

    # ---------- configuración ----------
    def _guardar(self):
        ia_config.save(self.repo, self.chk.isChecked(), self._modelo_elegido(), self.cb_modo.currentData(),
                       engine=self._motor_elegido())
        self.settings_changed.emit()
        self.refresh()
        self._set_msg("Configuración guardada.")

    def _probar(self):
        modelo = self._modelo_elegido()
        if self._motor_elegido() == "paquete":
            if not paquete.instalado(modelo):
                self._set_msg(f"Primero descargue {paquete.MODELOS[modelo]['nombre']} arriba.", ok=False)
                return
        else:
            try:
                instalados = list_models()
            except OllamaError:
                self._set_msg("No se detectó Ollama. Inicie Ollama e inténtelo de nuevo.", ok=False)
                return
            if not has_model(instalados, modelo):
                self._set_msg(f"El modelo {modelo} no está instalado. En una terminal ejecute: "
                              f"ollama pull {modelo}", ok=False)
                return
        self._set_msg("Probando el modelo…")
        self.test_panel.start(modelo, prompts.test_messages())

    def _preguntar(self):
        pregunta = self.pregunta.text().strip()
        if not pregunta:
            self.soporte.mostrar_mensaje("Escriba una pregunta.", error=True)
            return
        ok, model, msg = ia_config.check_ai(self.repo)
        if not ok:
            self.soporte.mostrar_mensaje(msg, error=True)
            return
        reglas = prompts.relevant_rules(pregunta, load_rules())
        self.soporte.start(model, prompts.support_messages(pregunta, reglas))

    def shutdown(self):
        self.test_panel.shutdown()
        self.soporte.shutdown()
        if self._ocupado():
            self.descarga.cancel()
            self.descarga.wait(10000)
