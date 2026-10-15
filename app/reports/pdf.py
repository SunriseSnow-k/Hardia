"""Generación de reportes en PDF (ReportLab). Funciona sin Internet.

Los dos reportes (técnico y para el cliente) salen de los MISMOS datos fuente:
la última captura de hardware del caso, el diagnóstico guardado y las notas.
Nunca se inventan datos: lo que no se pudo leer aparece con su motivo.
"""
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from app.db.clients_repo import ClientsRepository
from app.db.hardware_repo import ORIGENES, HardwareRepository
from app.db.health_repo import HealthRepository
from app.db.notes_repo import TIPOS, TIPOS_CLIENTE, NotesRepository
from app.db.orders_repo import OrdersRepository
from app.diagnosis.engine import diagnose
from app.hardware.inventory import (CATEGORIAS, ESTADO_TEXTO, OK, compare_captures,
                                    fmt_bytes, fuente_salud, inventory_rows)
from app.health import SIN_REF
from app.health.benchmark import texto_condiciones

AZUL = colors.HexColor("#1f6f8b")
AZUL_CLARO = colors.HexColor("#e1f0f5")
GRIS = colors.HexColor("#66727f")
LINEA = colors.HexColor("#d9dfe5")
TEXTO = colors.HexColor("#1b2430")
PRIO_HEX = {"Alta": "#c0392b", "Media": "#b7791f", "Baja": "#2f855a"}
ESTADO_HEX = {"Atención": "#c0392b", "Revisar": "#b7791f", "Buen estado": "#2f855a", "Sin referencia": "#5f6b77"}
URGENCIA = {"Alta": "Conviene atenderlo pronto", "Media": "Conviene revisarlo",
            "Baja": "No es urgente"}
ANCHO = 170  # mm útiles en A4 con márgenes de 20 mm

# Qué significa cada posible causa, en palabras simples (reporte para el cliente).
IMPLICACIONES = {
    "R-001": "El equipo se calienta más de lo normal. Si no se atiende, puede apagarse solo, "
             "volverse lento y acortar la vida de sus componentes.",
    "R-002": "La ventilación no está enfriando bien el equipo; esto puede causar lentitud "
             "o apagados repentinos.",
    "R-003": "El procesador trabaja casi al máximo de forma constante; por eso el equipo responde lento.",
    "R-004": "La memoria del equipo se llena con lo que está abierto; al quedarse sin memoria, "
             "todo se vuelve lento.",
    "R-005": "El equipo tiene poca memoria para el uso que se le da; ampliarla suele mejorar la rapidez.",
    "R-006": "Queda poco espacio en el disco. Con el disco casi lleno el sistema se vuelve lento "
             "y las actualizaciones pueden fallar.",
    "R-007": "La unidad donde se guardan sus archivos muestra señales de desgaste. "
             "Le recomendamos respaldar su información cuanto antes.",
    "R-008": "El disco es de tipo mecánico, más lento que los discos de estado sólido (SSD).",
    "R-009": "Muchos programas se abren solos al encender, lo que hace lento el arranque y el uso diario.",
    "R-010": "Puede haber un problema con la alimentación eléctrica (cargador, fuente o conexión), "
             "lo que explicaría que no encienda o se apague.",
    "R-011": "Los reinicios pueden deberse a la memoria o a la alimentación; hay que confirmarlo con pruebas.",
    "R-012": "Una actualización o un controlador (el programa que maneja una pieza del equipo) "
             "puede estar causando las fallas.",
    "R-013": "Puede haber programas no deseados o dañinos que hacen lento el equipo "
             "o ponen en riesgo su información.",
    "R-014": "La parte que maneja la imagen (tarjeta o controlador de video) podría estar fallando.",
    "R-015": "La tarjeta de video se calienta demasiado; puede provocar cierres de juegos o programas, "
             "fallas de imagen y acortar su vida útil.",
    "R-016": "Un ventilador no está girando, así que el equipo no se enfría bien y puede apagarse "
             "o dañarse por calor.",
    "R-017": "El procesador se calienta incluso sin trabajo pesado; suele deberse a polvo o pasta "
             "térmica seca.",
    "R-018": "La unidad de estado sólido (SSD) se acerca al final de su vida útil. Le recomendamos "
             "respaldar su información y planificar su cambio.",
    "R-019": "Windows detectó fallas en la unidad donde se guardan sus archivos. Respalde su "
             "información cuanto antes.",
    "R-020": "La unidad de almacenamiento trabaja muy caliente, lo que puede volverla lenta y "
             "reducir su vida útil.",
}
IMPLICACION_GENERICA = "Nuestro técnico le explicará qué significa y cómo resolverlo."


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


# ---------------- Datos ----------------
def _agrupar(filas: list[dict]) -> tuple[list, list]:
    """Separa el inventario en (categorías con datos, datos no disponibles)."""
    orden = [t for _k, t in CATEGORIAS]
    grupos: dict[str, list] = {}
    faltan = []
    for f in filas:
        if f["status"] == OK:
            grupos.setdefault(f["category"], []).append(f)
        else:
            faltan.append(f)
    claves = sorted(grupos, key=lambda c: orden.index(c) if c in orden else len(orden))
    return [(c, grupos[c]) for c in claves], faltan


def load_report_data(repo, code: str) -> dict:
    """Reúne todo lo necesario para ambos reportes. Si el caso no tiene diagnóstico
    guardado, se calcula con las reglas en ese momento (y así se indica)."""
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    hw = HardwareRepository(repo)
    capturas = hw.captures_for_case(code)
    captura = hw.get_capture(capturas[0]["id"]) if capturas else None
    scan = captura["payload"] if captura else repo.get_scan(code)
    if not isinstance(scan, dict):
        scan = None

    anterior, cambios = None, []
    eq = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (code,)).fetchone()[0]
    previa = hw.latest_capture(eq, exclude_case=code)
    if previa and scan and isinstance(previa.get("payload"), dict):
        anterior = {"case_code": previa["case_code"], "captured_at": previa["captured_at"]}
        cambios = compare_captures(previa["payload"], scan)

    d = repo.get_diagnosis(code)
    if d:
        result, method, fecha, saved = d["result"], d["method"], d["created_at"], True
    else:
        result, method, fecha, saved = diagnose(caso["problem"], scan), "Reglas", None, False

    filas = inventory_rows(scan) if scan else []
    categorias, no_disponible = _agrupar(filas)
    hr = HealthRepository(repo)
    try:  # mismos datos que la pantalla Salud del equipo; aquí no se guarda una evaluación nueva
        sal = hr.evaluate_case(code, guardar=False)
        salud = {"resultado": sal["resultado"], "benchmark": sal.get("benchmark"),
                 "incluidos": hr.included_for_case(code)}
    except Exception as e:  # la salud nunca debe impedir generar el reporte
        salud = {"resultado": None, "benchmark": None, "incluidos": [], "error": str(e)}
    return {
        "caso": caso, "doc_id": ClientsRepository(repo).doc_for_case(code),
        "scan": scan,
        "capture": ({"id": captura["id"], "captured_at": captura["captured_at"],
                     "source": captura["source"], "source_file": captura["source_file"],
                     "count": len(capturas)} if captura else None),
        "categories": categorias, "unavailable": no_disponible,
        "previous": anterior, "changes": cambios,
        "result": result, "method": method, "diag_date": fecha, "diag_saved": saved,
        "notes": [dict(n) for n in NotesRepository(repo).for_case(code)],
        "health": salud,
        "business": repo.get_setting("business_name", "Mi taller"),
        "phone": repo.get_setting("business_phone", ""),
    }


def client_summary(result: dict, max_items: int = 3) -> list[tuple[str, str]]:
    """Causas en lenguaje simple para el cliente: (causa, urgencia)."""
    return [(c["cause"], URGENCIA.get(c["priority"], ""))
            for c in result.get("causes", [])[:max_items]]


def implication(cause: dict) -> str:
    return IMPLICACIONES.get(cause.get("id"), IMPLICACION_GENERICA)


def _fecha(valor, largo: int = 16) -> str:
    """'2026-10-06T09:15:00' -> '06/10/2026 09:15' (largo 10 -> solo la fecha).
    Si el texto no tiene el formato esperado se muestra tal cual, recortado."""
    t = str(valor or "").replace("T", " ")
    try:
        dt = datetime.strptime(t[:16], "%Y-%m-%d %H:%M") if len(t) >= 16 else datetime.strptime(t[:10], "%Y-%m-%d")
    except ValueError:
        return t[:largo]
    return dt.strftime("%d/%m/%Y" if largo <= 10 or len(t) < 16 else "%d/%m/%Y %H:%M")


def measured_items(scan: dict | None) -> list[tuple[str, str]]:
    """Lo que medimos, en palabras simples. Solo incluye datos realmente leídos."""
    inv = _d(_d(scan).get("inventory"))
    if not inv:  # escaneo antiguo: se usa la lista de componentes tal como se leyó
        return [(c.get("name", "?"), c.get("detail", "")) for c in _l(_d(scan).get("components"))
                if isinstance(c, dict) and c.get("status") == "ok" and c.get("detail")]
    items = []
    ident = _d(inv.get("identity"))
    marca = " ".join(p for p in (ident.get("manufacturer"), ident.get("model")) if p)
    if marca:
        items.append(("Equipo", marca))
    cpu = _d(inv.get("cpu"))
    if cpu.get("name"):
        items.append(("Procesador", cpu["name"]))
    mem = _d(inv.get("memory"))
    if mem.get("total_gb"):
        uso = f' (en uso {mem["used_pct"]:.0f} % al momento de la revisión)' if mem.get("used_pct") is not None else ""
        items.append(("Memoria RAM", f'{round(mem["total_gb"])} GB{uso}'))
    sto = _d(inv.get("storage"))
    for u in _l(sto.get("physical")):
        if not isinstance(u, dict) or not u.get("size_bytes"):
            continue
        tipo = u.get("media") or "Unidad"
        estado = (f' — estado: {u["health"]} ({fuente_salud(u.get("health_source"))})'
                  if u.get("health") else "")
        items.append(("Disco", f'{tipo} de {fmt_bytes(u["size_bytes"])}{estado}'))
    for v in _l(sto.get("logical")):
        if isinstance(v, dict) and v.get("size_bytes") and v.get("free_bytes") is not None:
            items.append((f'Espacio libre en {v.get("drive", "el disco")}',
                          f'{fmt_bytes(v["free_bytes"])} de {fmt_bytes(v["size_bytes"])}'))
    sen = _d(inv.get("sensors"))
    temp = _d(scan.get("metrics")).get("cpu_temp")
    if temp is not None:
        fuente = sen.get("cpu_temp_source")
        nota = "" if fuente == "LibreHardwareMonitor" else " (sensor general del equipo; valor aproximado)"
        items.append(("Temperatura", f"{float(temp):.0f} °C{nota}"))
    bat = _d(inv.get("battery"))
    if bat.get("wear_pct") is not None:
        items.append(("Batería", f'desgaste estimado {bat["wear_pct"]:.0f} %'))
    so = _d(inv.get("os"))
    if so.get("name"):
        items.append(("Sistema operativo", so["name"]))
    return items


# ---------------- Estilos y utilidades ----------------
def _styles() -> dict:
    base = dict(fontName="Helvetica", fontSize=10, leading=14, textColor=TEXTO)

    def est(nombre, **extra):
        return ParagraphStyle(nombre, **{**base, **extra})

    return {
        "body": est("body"),
        "cell": est("cell", fontSize=9, leading=12),
        "small": est("small", fontSize=8.5, leading=11, textColor=GRIS),
        "label": est("label", fontSize=9, leading=12, textColor=GRIS, fontName="Helvetica-Bold"),
        "head": est("head", fontSize=9, leading=12, textColor=colors.white, fontName="Helvetica-Bold"),
        "cat": est("cat", fontSize=9.5, leading=12, textColor=AZUL, fontName="Helvetica-Bold"),
        "biz": est("biz", fontSize=10, textColor=GRIS, fontName="Helvetica-Bold"),
        "h1": est("h1", fontSize=17, leading=21, textColor=AZUL, fontName="Helvetica-Bold"),
        "h2": est("h2", fontSize=12, leading=16, fontName="Helvetica-Bold",
                  spaceBefore=12, spaceAfter=5, keepWithNext=1),
        "h3": est("h3", fontSize=10.5, leading=14, fontName="Helvetica-Bold",
                  spaceBefore=6, spaceAfter=2, keepWithNext=1),
    }


def _e(texto) -> str:
    return escape(str(texto if texto is not None else ""))


def _p(texto, estilo, raw: bool = False) -> Paragraph:
    return Paragraph(texto if raw else _e(texto), estilo)


def _prio(p: str) -> str:
    return f'<font color="{PRIO_HEX.get(p, "#1b2430")}"><b>{_e(p)}</b></font>'


def _kv(filas, st) -> Table:
    datos = [[_p(k, st["label"]), _p(v or "—", st["cell"])] for k, v in filas]
    t = Table(datos, colWidths=[40 * mm, (ANCHO - 40) * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _estilo_tabla(extra=()) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("GRID", (0, 0), (-1, -1), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        *extra,
    ])


def _tabla(encabezado, filas, anchos_mm, st) -> Table:
    datos = [[_p(h, st["head"]) for h in encabezado]] + filas
    t = Table(datos, colWidths=[a * mm for a in anchos_mm], repeatRows=1)
    t.setStyle(_estilo_tabla())
    return t


def _tabla_categoria(titulo: str, filas: list[dict], st) -> Table:
    """Tabla de una categoría: el título y el encabezado se repiten si cambia de página."""
    datos = [[_p(titulo, st["cat"]), ""],
             [_p("Dato", st["head"]), _p("Valor", st["head"])]]
    datos += [[_p(f["label"], st["cell"]), _p(f["value"], st["cell"])] for f in filas]
    t = Table(datos, colWidths=[52 * mm, (ANCHO - 52) * mm], repeatRows=2)
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), AZUL_CLARO),
        ("BACKGROUND", (0, 1), (-1, 1), AZUL),
        ("GRID", (0, 1), (-1, -1), 0.4, LINEA),
        ("BOX", (0, 0), (-1, 0), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _aviso(texto: str, st) -> Table:
    t = Table([[_p(texto, st["cell"])]], colWidths=[ANCHO * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf0d9")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#b7791f")),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _cabecera(data: dict, st: dict, titulo: str, extra=()) -> list:
    caso = data["caso"]
    return [
        _p(data["business"], st["biz"]), _p(titulo, st["h1"]), Spacer(1, 4 * mm),
        _kv([("Caso", caso["code"]),
             ("Fecha de ingreso", _fecha(caso["created_at"])),
             ("Reporte generado", datetime.now().strftime("%d/%m/%Y %H:%M")), *extra], st),
    ]


def _origen_captura(cap: dict) -> str:
    texto = ORIGENES.get(cap["source"], cap["source"])
    if cap.get("source_file"):
        texto += f' ({cap["source_file"]})'
    return texto


def _canvas_numerado(pie: str):
    """Canvas que escribe 'Página X de N' (necesita conocer el total al final)."""

    class _Canvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._estados = []

        def showPage(self):
            self._estados.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._estados)
            for estado in self._estados:
                self.__dict__.update(estado)
                self._pie(total)
                super().showPage()
            super().save()

        def _pie(self, total: int):
            self.saveState()
            self.setStrokeColor(LINEA)
            self.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
            self.setFont("Helvetica", 8)
            self.setFillColor(GRIS)
            self.drawString(20 * mm, 10 * mm, pie)
            self.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Página {self._pageNumber} de {total}")
            self.restoreState()

    return _Canvas


def _construir(story: list, path, titulo: str, autor: str, code: str) -> None:
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm, title=titulo,
        author=autor or "Sistema Inteligente Offline",
    )
    pie = f"Sistema Inteligente Offline · Caso {code} · Documento generado localmente"
    doc.build(story, canvasmaker=_canvas_numerado(pie))


# ---------------- Reporte técnico ----------------
def _seccion_inventario(data: dict, st: dict) -> list:
    story = [_p("Inventario de hardware", st["h2"])]
    cap = data["capture"]
    if not data["scan"]:
        return story + [_p("Este caso no tiene captura de hardware. Escanee el equipo o importe "
                           "su archivo .diag para incluir el inventario.", st["small"])]
    if cap:
        story.append(_p(f'Captura del {_e(_fecha(cap["captured_at"]))} · Origen: {_e(_origen_captura(cap))}'
                        + (f' · El caso tiene {cap["count"]} capturas; se usa la más reciente.'
                           if cap["count"] > 1 else ""), st["small"], raw=True))
    else:
        story.append(_p(f'Escaneo del caso del {_e(_fecha(data["scan"].get("scanned_at")))}.',
                        st["small"], raw=True))
    story.append(Spacer(1, 2 * mm))
    if not data["categories"]:
        story.append(_p("La captura no contiene datos leídos.", st["body"]))
    for titulo, filas in data["categories"]:
        story.append(_tabla_categoria(titulo, filas, st))
        story.append(Spacer(1, 3 * mm))

    story.append(_p("Información no disponible", st["h3"]))
    if data["unavailable"]:
        filas = []
        for f in data["unavailable"]:
            dato = "Toda la categoría" if f["label"] == "Estado de la detección" else f["label"]
            motivo = f["value"] or ESTADO_TEXTO.get(f["status"], f["status"])
            filas.append([_p(f["category"], st["cell"]), _p(dato, st["cell"]), _p(motivo, st["cell"])])
        story.append(_tabla(["Categoría", "Dato", "Motivo"], filas, [42, 58, ANCHO - 100], st))
    else:
        story.append(_p("Todos los datos previstos se pudieron leer.", st["small"]))
    return story


def _seccion_cambios(data: dict, st: dict, cliente: bool = False) -> list:
    titulo = "Cambios desde su visita anterior" if cliente else "Cambios desde la inspección anterior"
    prev = data["previous"]
    if not prev:
        if cliente:
            return []
        return [_p(titulo, st["h2"]),
                _p("No hay inspecciones anteriores de este equipo con las que comparar.", st["small"])]
    story = [_p(titulo, st["h2"])]
    base = (f'Comparado con la revisión del {_fecha(prev["captured_at"], 10)}.' if cliente else
            f'Comparado con la captura del {_fecha(prev["captured_at"])} (caso {prev["case_code"]}).')
    story.append(_p(base, st["small"]))
    story.append(Spacer(1, 1.5 * mm))
    if data["changes"]:
        filas = [[_p(c["area"], st["cell"]), _p(c["antes"], st["cell"]), _p(c["despues"], st["cell"])]
                 for c in data["changes"]]
        story.append(_tabla(["Área", "Antes", "Ahora"], filas, [45, 62, ANCHO - 107], st))
    else:
        story.append(_p("No se encontraron cambios en los datos que se pueden comparar.", st["body"]))
    return [KeepTogether(story)]


def _estado_txt(estado: str) -> str:
    return f'<font color="{ESTADO_HEX.get(estado, "#1b2430")}"><b>{_e(estado)}</b></font>'


def _seccion_salud(data: dict, st: dict) -> list:
    """Salud frente a fábrica (reporte técnico): índice, componentes, prueba e inclusiones."""
    story = [_p("Salud frente a fábrica", st["h2"])]
    salud = _d(data.get("health"))
    res = salud.get("resultado")
    if not res or not res.get("componentes"):
        motivo = salud.get("error") or (res or {}).get("aviso") or "No hay datos de salud para este caso."
        return story + [_p(motivo, st["small"])]
    ind = res["indice"]
    if ind["valor"] is not None:
        story.append(_p(f'Índice orientativo: <b>{ind["valor"]:.0f} %</b> respecto a fábrica '
                        f'({_estado_txt(ind["estado"])}) · promedio simple de: {_e(", ".join(ind["incluidos"]))}.',
                        st["body"], raw=True))
    else:
        story.append(_p("No se calculó el índice: ningún componente tiene a la vez medición y referencia "
                        "de fábrica.", st["body"]))
    story.append(Spacer(1, 2 * mm))
    filas = []
    for c in res["componentes"]:
        respecto = f'{c["pct"]:.0f} %' if c.get("pct") is not None else (c.get("alt") or SIN_REF)
        filas.append([
            _p(f'<b>{_e(c["nombre"])}</b><br/><font size="8" color="#5f6b77">{_e(c.get("modelo", ""))}</font>',
               st["cell"], raw=True),
            _p(_estado_txt(c["estado"]), st["cell"], raw=True),
            _p(f'{_e(c["medido"]["valor"])}<br/><font size="8" color="#5f6b77">{_e(c["medido"]["nota"])}</font>',
               st["cell"], raw=True),
            _p(f'{_e(c["fabrica"]["valor"])}<br/><font size="8" color="#5f6b77">{_e(c["fabrica"]["nota"])}</font>',
               st["cell"], raw=True),
            _p(respecto, st["cell"]),
            _p(c.get("fuente") or "—", st["small"]),
        ])
    story.append(_tabla(["Componente", "Estado", "Medido", "De fábrica", "Respecto a fábrica", "Fuente"],
                        filas, [30, 20, 30, 30, 26, ANCHO - 136], st))
    if res.get("hallazgo"):
        story.append(Spacer(1, 2 * mm))
        story.append(_p(f'Lo más importante: {res["hallazgo"]["texto"]}', st["body"]))

    bench = salud.get("benchmark")
    story.append(_p("Prueba de rendimiento", st["h3"]))
    if bench:
        story.append(_p(f'Realizada el {_fecha(bench.get("fecha"))}. Condiciones en que se midió:', st["small"]))
        story.append(_kv(texto_condiciones(bench.get("condiciones")), st))
        cpu = _d(bench.get("cpu"))
        if cpu.get("detenido_por_temp"):
            story.append(_p(f'La prueba de CPU se detuvo por seguridad al llegar a {cpu.get("temp_max", 0):.0f} °C.',
                            st["body"]))
        for d in _l(bench.get("discos")):
            if isinstance(d, dict) and not d.get("lectura_mb_s"):
                story.append(_p(f'Disco {d.get("model") or d.get("index")}: lectura no disponible '
                                f'({d.get("motivo") or "sin datos"}).', st["small"]))
    else:
        story.append(_p("No se ejecutó la prueba de rendimiento: el procesador y la velocidad de los discos "
                        "quedan sin medición.", st["small"]))
    if salud.get("incluidos"):
        story.append(_p("Incluido en el diagnóstico por el técnico", st["h3"]))
        for i in salud["incluidos"]:
            story.append(_p(f'• {i["texto"]}', st["body"]))
    story.append(_p("El índice es orientativo: compara cada componente con su valor de fábrica usando solo datos "
                    "leídos o medidos; la validación final es del técnico.", st["small"]))
    return story


def salud_para_cliente(data: dict) -> list[tuple[str, str]]:
    """Componentes con estado conocido, en palabras simples (sin datos técnicos internos)."""
    res = _d(_d(data.get("health")).get("resultado"))
    items = []
    ind = _d(res.get("indice"))
    if ind.get("valor") is not None:
        items.append(("Estado general (orientativo)", f'{ind["valor"]:.0f} % respecto a un equipo nuevo'))
    for c in _l(res.get("componentes")):
        if c.get("estado") == SIN_REF or not c.get("cliente"):
            continue
        extra = f' ({c["pct"]:.0f} % respecto a fábrica)' if c.get("pct") is not None else ""
        items.append((c["nombre"], f'{c["estado"]}{extra}. {c["cliente"]}'))
    return items


def _seccion_notas(notas: list[dict], st: dict) -> list:
    filas = [[_p(_fecha(n["created_at"]), st["cell"]), _p(TIPOS.get(n["kind"], n["kind"]), st["cell"]),
              _p(n["author"] or "—", st["cell"]), _p(n["text"], st["cell"])] for n in notas]
    return [_tabla(["Fecha", "Tipo", "Técnico", "Nota"], filas, [28, 32, 22, ANCHO - 82], st)]


def build_technical(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, res = data["caso"], data["result"]
    story = _cabecera(data, st, "Reporte técnico de diagnóstico")

    story.append(_p("Cliente y equipo", st["h2"]))
    story.append(_kv([
        ("Cliente", caso["cliente"]), ("Documento", data["doc_id"]), ("Teléfono", caso["phone"]),
        ("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"]),
        ("Estado del caso", caso["status"]), ("Prioridad", caso["priority"]),
    ], st))

    story.append(_p("Problema reportado", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))

    story += _seccion_inventario(data, st)
    story += _seccion_cambios(data, st)
    story += _seccion_salud(data, st)

    bloque = [_p("Resultado del diagnóstico", st["h2"])]
    origen = (f'Diagnóstico guardado el {_fecha(data["diag_date"])}.' if data["diag_saved"]
              else "El diagnóstico se calculó al generar este reporte (no se había guardado).")
    bloque.append(_p(f'Estado general: <b>{_e(res.get("status", ""))}</b> · '
                     f'Método de análisis: {_e(data["method"])}', st["body"], raw=True))
    bloque.append(_p(origen, st["small"]))
    bloque.append(Spacer(1, 2 * mm))
    causas = res.get("causes", [])
    if causas:
        filas = []
        for i, c in enumerate(causas, 1):
            filas.append([
                _p(str(i), st["cell"]), _p(c["cause"], st["cell"]),
                _p(_prio(c["priority"]), st["cell"], raw=True),
                _p(f'{c.get("confidence_label", "")} ({round(c.get("confidence", 0) * 100)} %)', st["cell"]),
                _p("; ".join(c.get("evidence", [])), st["cell"]),
            ])
        bloque.append(_tabla(["N.º", "Posible causa", "Prioridad", "Confianza", "Evidencia"],
                             filas, [9, 52, 20, 22, 67], st))
    else:
        bloque.append(_p("No se identificaron causas con los datos disponibles.", st["body"]))
    story.append(KeepTogether(bloque))

    recs = res.get("recommendations", [])
    if recs:
        story.append(_p("Recomendaciones", st["h2"]))
        for i, r in enumerate(recs, 1):
            story.append(_p(f"{i}. {r}", st["body"]))

    if res.get("ai_analysis"):
        story.append(_p("Análisis de IA local (asistencia)", st["h2"]))
        story.append(_p(res["ai_analysis"], st["body"]))
        if res.get("ai_model"):
            story.append(_p(f'Modelo local utilizado: {res["ai_model"]}', st["small"]))

    story.append(_p("Notas del caso", st["h2"]))
    if data["notes"]:
        story += _seccion_notas(data["notes"], st)
    else:
        story.append(_p("No hay notas registradas.", st["small"]))

    story.append(Spacer(1, 5 * mm))
    story.append(KeepTogether([
        _aviso(res.get("disclaimer", "El resultado es una asistencia y debe ser validado por el técnico."), st),
        Spacer(1, 12 * mm),
        _p("Técnico responsable: ______________________________", st["body"]),
        _p(f"ID de técnico: {tech_id or '—'}", st["small"]),
    ]))
    _construir(story, path, f'Reporte técnico {caso["code"]}', tech_id, caso["code"])


# ---------------- Reporte para el cliente ----------------
def build_client(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, res = data["caso"], data["result"]
    story = _cabecera(data, st, "Informe de revisión de su equipo")

    story.append(Spacer(1, 4 * mm))
    story.append(_p(f'Estimado/a {caso["cliente"] or "cliente"}:', st["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_p("Gracias por confiarnos su equipo. Este es el resumen de nuestra revisión.", st["body"]))
    story.append(Spacer(1, 3 * mm))
    filas = [("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"])]
    if data["doc_id"]:
        filas.insert(0, ("Documento", data["doc_id"]))
    story.append(_kv(filas, st))

    story.append(_p("Lo que nos comentó", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))

    story.append(_p("Lo que medimos", st["h2"]))
    medidos = measured_items(data["scan"])
    if medidos:
        cuando = _fecha((data["capture"] or {}).get("captured_at") or _d(data["scan"]).get("scanned_at"), 10)
        story.append(_p(f"Datos leídos de su equipo el {cuando}:",
                        ParagraphStyle("intro", parent=st["body"], keepWithNext=1)))
        story.append(Spacer(1, 1.5 * mm))
        story.append(_kv(medidos, st))
        if data["unavailable"]:
            faltan = sorted({f["category"] for f in data["unavailable"]})
            story.append(Spacer(1, 1.5 * mm))
            story.append(_p("Algunos datos no se pudieron leer automáticamente ("
                            + ", ".join(faltan) + "). El técnico los revisará si hace falta.", st["small"]))
    else:
        story.append(_p("En esta revisión no se tomaron mediciones automáticas de su equipo.", st["body"]))
    salud = salud_para_cliente(data)
    if salud:
        story.append(_p("Estado de los componentes", st["h3"]))
        story.append(_kv(salud, st))
        story.append(_p("Comparamos cada componente con su valor de fábrica usando solo datos medidos; "
                        "es una orientación.", st["small"]))

    story.append(_p("Lo que encontramos", st["h2"]))
    causas = res.get("causes", [])[:3]
    if causas:
        story.append(_p("Estas son las causas más probables de la falla:", st["body"]))
        for c in causas:
            story.append(Spacer(1, 1.5 * mm))
            story.append(_p(f'• <b>{_e(c["cause"])}</b> — {_e(URGENCIA.get(c["priority"], ""))}',
                            st["body"], raw=True))
            story.append(_p(f"Qué significa: {implication(c)}", st["cell"]))
        story.append(Spacer(1, 1.5 * mm))
        story.append(_p("Se trata de posibles causas: nuestro técnico las confirmará con pruebas.", st["small"]))
    else:
        story.append(_p("Todavía no identificamos una causa con los datos disponibles. "
                        "Necesitamos revisar el equipo con más detalle en el taller.", st["body"]))

    story += _seccion_cambios(data, st, cliente=True)

    for kind, titulo in (("trabajo", "Trabajo realizado"), ("cliente", "Notas del técnico para usted")):
        notas = [n for n in data["notes"] if n["kind"] == kind and kind in TIPOS_CLIENTE]
        if notas:
            story.append(_p(titulo, st["h2"]))
            for n in notas:
                story.append(_p(f'• {_e(n["text"])} <font color="#66727f" size="8.5">'
                                f'({_e(_fecha(n["created_at"], 10))})</font>', st["body"], raw=True))

    recs = res.get("recommendations", [])[:5]
    if recs:
        story.append(_p("Lo que recomendamos", st["h2"]))
        for i, r in enumerate(recs, 1):
            story.append(_p(f"{i}. {r}", st["body"]))

    contacto = data["business"] + (f' · Teléfono: {data["phone"]}' if data["phone"] else "")
    story.append(Spacer(1, 6 * mm))
    story.append(KeepTogether([
        _aviso("Este informe es una orientación y no incluye precios ni plazos. "
               "Nos comunicaremos con usted para acordarlos antes de realizar cualquier trabajo.", st),
        Spacer(1, 6 * mm),
        _p("Atentamente,", st["body"]),
        _p(contacto, st["body"]),
        _p(f"Técnico: {tech_id or '—'}", st["small"]),
    ]))
    _construir(story, path, f'Informe para el cliente {caso["code"]}', tech_id, caso["code"])


# ---------------- Orden de servicio ----------------
def load_order_data(repo, code: str) -> dict:
    """Datos de la orden de servicio: solo lo registrado en la recepción (sin diagnóstico)."""
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    orders = OrdersRepository(repo)
    orden = orders.get(code)
    return {
        "caso": caso, "doc_id": ClientsRepository(repo).doc_for_case(code),
        "order": dict(orden) if orden else {}, "terms": orders.terms(),
        "business": repo.get_setting("business_name", "Mi taller"),
        "phone": repo.get_setting("business_phone", ""),
    }


def _firmas(izquierda: str, derecha: str, st) -> Table:
    centrado = ParagraphStyle("firma", parent=st["small"], alignment=1)
    t = Table([["", "", ""], [_p(izquierda, centrado), "", _p(derecha, centrado)]],
              colWidths=[75 * mm, 20 * mm, 75 * mm], rowHeights=[16 * mm, None])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (0, 0), 0.6, TEXTO), ("LINEBELOW", (2, 0), (2, 0), 0.6, TEXTO),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_order(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, orden = data["caso"], data["order"]
    contacto = data["business"] + (f' · Teléfono: {data["phone"]}' if data["phone"] else "")
    estimada = _fecha(orden["estimated_date"], 10) if orden.get("estimated_date") else "Por confirmar"
    story = [
        _p(contacto, st["biz"]), _p("Orden de servicio", st["h1"]), Spacer(1, 4 * mm),
        _kv([("N.º de orden", caso["code"]), ("Fecha de ingreso", _fecha(caso["created_at"])),
             ("Entrega estimada", estimada)], st),
    ]
    story.append(_p("Cliente", st["h2"]))
    story.append(_kv([("Nombre", caso["cliente"]), ("Documento", data["doc_id"]),
                      ("Teléfono", caso["phone"])], st))
    story.append(_p("Equipo recibido", st["h2"]))
    story.append(_kv([("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"]),
                      ("Accesorios", orden.get("accessories") or "Ninguno"),
                      ("Estado físico", orden.get("condition") or "Sin observaciones")], st))
    story.append(_p("Problema reportado por el cliente", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))
    if orden.get("observations"):
        story.append(_p("Observaciones de la recepción", st["h2"]))
        story.append(_p(orden["observations"], st["body"]))
    if data["terms"]:
        story.append(_p("Condiciones del servicio", st["h2"]))
        for i, t in enumerate(data["terms"], 1):
            story.append(_p(f"{i}. {t}", st["cell"]))
    recibido = orden.get("received_by") or tech_id or ""
    story.append(Spacer(1, 8 * mm))
    story.append(KeepTogether([
        _p("Con su firma, el cliente declara que entrega el equipo en el estado descrito y acepta las "
           "condiciones del servicio.", st["small"]),
        Spacer(1, 4 * mm),
        _firmas("Firma del cliente", f"Recibido por{': ' + recibido if recibido else ''}", st),
    ]))
    _construir(story, path, f'Orden de servicio {caso["code"]}', tech_id, caso["code"])
