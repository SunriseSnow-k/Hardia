"""Diálogo de la prueba de rendimiento: condiciones, pasos, temperatura en vivo y cancelación.
La medición corre en un QThread (app/health/benchmark.py); la interfaz nunca se bloquea."""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from app.db.health_repo import HealthRepository
from app.hardware.scanner import LectorTemperatura
from app.health import benchmark as bm
from app.ui.pages.escaneo import fila_html
from app.ui.widgets import lista_dato_valor, muted, panel


def discos_de_captura(scan: dict) -> list[dict]:
    sto = ((scan or {}).get("inventory") or {}).get("storage") or {}
    return [{"index": u.get("index"), "model": u.get("model")} for u in sto.get("physical") or []
            if isinstance(u, dict) and not u.get("external") and u.get("index") is not None]


class BenchmarkWorker(QThread):
    paso = Signal(int, str)
    muestra = Signal(float, float, object, object)  # t, ops/s, temp, fuente
    avance_disco = Signal(int, float, int)
    terminado = Signal(dict)
    fallo = Signal(str)

    def __init__(self, discos, duracion_cpu, duracion_disco, procesos, cond, lector):
        super().__init__()
        self.discos, self.cond, self.lector = discos, cond, lector
        self.duracion_cpu, self.duracion_disco, self.procesos = duracion_cpu, duracion_disco, procesos
        self._cancelar = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        try:
            with self.lector() as lt:
                res = bm.ejecutar(
                    self.discos, cancelado=lambda: self._cancelar,
                    al_paso=lambda i, t: self.paso.emit(i, t),
                    al_muestrear=lambda t, r, temp, f: self.muestra.emit(t, r, temp, f),
                    al_avanzar_disco=lambda i, t, b: self.avance_disco.emit(i, t, b),
                    leer_temp=lt.leer, duracion_cpu=self.duracion_cpu, duracion_disco=self.duracion_disco,
                    procesos=self.procesos, cond=self.cond)
            self.terminado.emit(res)
        except Exception as e:  # nunca debe cerrar el programa
            self.fallo.emit(str(e))


class BenchmarkDialog(QDialog):
    def __init__(self, repo, code: str, captura: dict, parent=None, duracion_cpu: float = bm.DURACION_CPU,
                 duracion_disco: float = bm.DURACION_DISCO, procesos: int | None = None,
                 lector=LectorTemperatura, condiciones=None):
        super().__init__(parent)
        self.repo, self.code, self.captura = repo, code, captura
        self.saved = False
        self.resultado: dict | None = None
        self.worker: BenchmarkWorker | None = None
        self._lector = lector
        self._duraciones = (duracion_cpu, duracion_disco, procesos)
        self.discos = discos_de_captura(captura["payload"])
        self.cond = condiciones if condiciones is not None else bm.condiciones()
        with lector() as lt:
            self.temp_inicial, self.fuente_inicial = lt.leer()

        self.setWindowTitle(f"Prueba de rendimiento — {code}")
        self.resize(720, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(10)
        t = QLabel("Prueba de rendimiento")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        total = duracion_cpu + duracion_disco * len(self.discos)
        lay.addWidget(muted(f"Mide este equipo durante unos {total:.0f} s. El procesador trabajará al máximo y "
                            "los discos se leerán sin escribir nada ni abrir archivos del cliente."))

        aviso = QFrame()
        aviso.setObjectName("Alert")
        av = QVBoxLayout(aviso)
        av.setContentsMargins(14, 10, 14, 10)
        txt = ("<b>Antes de empezar:</b> conecte el cargador y cierre los programas abiertos. La prueba se "
               f"detiene sola si la CPU llega a {bm.CORTE_TEMP:.0f} °C. La lectura de discos necesita "
               "ejecutar el programa como administrador; sin ese permiso se omite y se indica el motivo.")
        a1 = QLabel(txt)
        a1.setTextFormat(Qt.RichText)
        a1.setWordWrap(True)
        av.addWidget(a1)
        self.chk_sin_temp = QCheckBox("Entiendo que sin lectura de temperatura no hay corte de seguridad")
        if self.temp_inicial is None:
            a2 = QLabel("<b style='color:#c0392b'>No hay lectura de temperatura en este equipo:</b> el corte "
                        "a 95 °C no podrá actuar. Para tenerla, abra LibreHardwareMonitor antes de la prueba "
                        "o ejecute este programa como administrador (lectura aproximada del sensor ACPI). "
                        "Si continúa sin lectura, vigile el equipo y cancele si se calienta.")
            a2.setTextFormat(Qt.RichText)
            a2.setWordWrap(True)
            av.addWidget(a2)
            av.addWidget(self.chk_sin_temp)
        lay.addWidget(aviso)

        p_c, vc = panel("Condiciones")
        vc.addWidget(lista_dato_valor(bm.texto_condiciones(self.cond)))
        lay.addWidget(p_c)

        p_p, vp = panel("Pasos")
        self.pasos: list[QLabel] = []
        nombres = ["Procesador: carga de todos los núcleos"] + [
            f'Disco {d.get("model") or d.get("index")}: lectura secuencial (solo lectura)' for d in self.discos]
        self._nombres = nombres
        for n in nombres:
            l = QLabel(fila_html(n, "Pendiente", "pending"))
            l.setTextFormat(Qt.RichText)
            self.pasos.append(l)
            vp.addWidget(l)
        self.barra = QProgressBar()
        self.barra.setRange(0, max(1, int(total)))
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(8)
        self.barra.setStyleSheet("QProgressBar{background:#e6eaee;border:none;border-radius:4px;}"
                                 "QProgressBar::chunk{background:#1f6f8b;border-radius:4px;}")
        vp.addWidget(self.barra)
        self.temp_lbl = QLabel(self._texto_temp(self.temp_inicial, self.fuente_inicial))
        self.temp_lbl.setStyleSheet("font-weight:600;")
        vp.addWidget(self.temp_lbl)
        self.estado = muted("")
        vp.addWidget(self.estado)
        lay.addWidget(p_p)
        lay.addStretch()

        fila = QHBoxLayout()
        self.b_iniciar = QPushButton("Iniciar prueba")
        self.b_iniciar.setObjectName("Primary")
        self.b_iniciar.clicked.connect(self.iniciar)
        self.b_cancelar = QPushButton("Cancelar prueba")
        self.b_cancelar.setObjectName("Secondary")
        self.b_cancelar.setEnabled(False)
        self.b_cancelar.clicked.connect(self.cancelar)
        self.b_cerrar = QPushButton("Cerrar")
        self.b_cerrar.setObjectName("Secondary")
        self.b_cerrar.clicked.connect(self.reject)
        for b in (self.b_iniciar, self.b_cancelar, self.b_cerrar):
            fila.addWidget(b)
        fila.addStretch()
        lay.addLayout(fila)
        if self.temp_inicial is None:
            self.b_iniciar.setEnabled(False)
            self.chk_sin_temp.toggled.connect(self.b_iniciar.setEnabled)

    @staticmethod
    def _texto_temp(temp, fuente) -> str:
        if temp is None:
            return "Temperatura de la CPU: sin lectura"
        aprox = "" if fuente == "LibreHardwareMonitor" else " (aproximada)"
        return f"Temperatura de la CPU: {float(temp):.0f} °C · {fuente or 's/d'}{aprox}"

    def _marcar(self, i: int, detalle: str, estado: str):
        if 0 <= i < len(self.pasos):
            self.pasos[i].setText(fila_html(self._nombres[i], detalle, estado))

    # ---------- ejecución ----------
    def iniciar(self):
        if self.worker and self.worker.isRunning():
            return
        dc, dd, pr = self._duraciones
        self.b_iniciar.setEnabled(False)
        self.b_cancelar.setEnabled(True)
        self.b_cerrar.setEnabled(False)
        self.estado.setText("Midiendo… no use el equipo mientras tanto.")
        self.worker = BenchmarkWorker(self.discos, dc, dd, pr, self.cond, self._lector)
        self.worker.paso.connect(self._on_paso)
        self.worker.muestra.connect(self._on_muestra)
        self.worker.avance_disco.connect(self._on_disco)
        self.worker.terminado.connect(self._on_fin)
        self.worker.fallo.connect(self._on_fallo)
        self.worker.start()

    def cancelar(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancelar()
            self.estado.setText("Cancelando…")
            self.b_cancelar.setEnabled(False)

    def _on_paso(self, i: int, _texto: str):
        if i > 0:
            self._marcar(i - 1, "Terminado", "ok")
        self._marcar(i, "En curso…", "running")

    def _on_muestra(self, t: float, ritmo: float, temp, fuente):
        self.barra.setValue(min(int(t), self.barra.maximum()))
        if temp is not None:
            self.temp_lbl.setText(self._texto_temp(temp, fuente))
            if float(temp) >= 90:
                self.temp_lbl.setStyleSheet("font-weight:600; color:#c0392b;")
        self._marcar(0, f"{t:.0f} s · {ritmo:,.0f} op/s".replace(",", " "), "running")

    def _on_disco(self, i: int, t: float, leidos: int):
        dc = self._duraciones[0]
        self.barra.setValue(min(int(dc + self._duraciones[1] * (i - 1) + t), self.barra.maximum()))
        self._marcar(i, f"{t:.0f} s · {leidos / 1e6:,.0f} MB leídos".replace(",", " "), "running")

    def _on_fin(self, res: dict):
        self.resultado = res
        self.b_cancelar.setEnabled(False)
        self.b_cerrar.setEnabled(True)
        self.barra.setValue(self.barra.maximum())
        cpu = res.get("cpu") or {}
        if cpu:
            if cpu.get("detenido_por_temp"):
                self._marcar(0, f'Detenida por seguridad: la CPU llegó a {cpu.get("temp_max", 0):.0f} °C', "error")
            elif cpu.get("cancelado"):
                self._marcar(0, "Cancelada", "warn")
            else:
                sost = f' · sostenido {cpu["sostenido_pct"]:.0f} %' if cpu.get("sostenido_pct") is not None else ""
                self._marcar(0, f'{cpu["ops_s"]:,.0f} op/s{sost}'.replace(",", " "), "ok")
        for i, d in enumerate(res.get("discos", []), 1):
            if d.get("lectura_mb_s"):
                self._marcar(i, f'{d["lectura_mb_s"]:.0f} MB/s en {d["duracion_s"]:.0f} s', "ok")
            else:
                self._marcar(i, f'No disponible: {d.get("motivo") or "sin datos"}', "warn")
        if res.get("cancelado"):
            self.estado.setText("Prueba cancelada: no se guardó ningún resultado.")
            return
        HealthRepository(self.repo).save_benchmark(self.code, self.captura["id"], res)
        self.saved = True
        self.estado.setText("Prueba terminada y guardada. La salud del equipo se actualizó con estos datos.")

    def _on_fallo(self, mensaje: str):
        self.b_cancelar.setEnabled(False)
        self.b_cerrar.setEnabled(True)
        self.estado.setStyleSheet("color:#c0392b;")
        self.estado.setText(f"La prueba falló: {mensaje}")

    def done(self, r):
        if self.worker and self.worker.isRunning():
            self.worker.cancelar()
            self.worker.wait(15000)
        super().done(r)
