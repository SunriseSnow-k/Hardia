"""Parte C: notas, documento del cliente, búsqueda ampliada y PDF con el inventario real."""
import sqlite3

import pytest
from reportlab.pdfgen import canvas as rl_canvas

from app.db.clients_repo import ClientsRepository, normalize_doc
from app.db.database import Database
from app.db.hardware_repo import HardwareRepository
from app.db.notes_repo import NotesRepository
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.db.search_repo import SearchQueries
from app.diagnosis.engine import diagnose
from app.hardware.inventory import inventory_rows
from app.hardware.scanner import run_scan
from app.reports import base, cliente, tecnico
from app.reports.cliente import implication, measured_items
from app.reports.datos import load_report_data
from app.reports.service import generate_report
from tests.test_fase10b_hardware import _env, _psutil


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "t.db")
    r = Repository(db)
    yield r
    db.close()


def _scan(fecha="2026-10-06T09:00:00", **env):
    s = run_scan(env=_env(**env))
    s["scanned_at"] = fecha
    s["provenance"] = {"how": "local_scan", "file": None}
    return s


def _codigos(res):
    return [r["code"] for r in res["rows"]]


# ---------------- notas ----------------
def test_notas_del_caso(repo):
    n = NotesRepository(repo)
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    n.add(code, "observacion", "  Disipador obstruido  ", "tec-001")
    n.add(code, "trabajo", "Limpieza interna", "TEC-001")
    n.add(code, "cliente", "Use el equipo sobre una mesa")
    notas = n.for_case(code)
    assert [x["kind"] for x in notas] == ["observacion", "trabajo", "cliente"]
    assert notas[0]["text"] == "Disipador obstruido" and notas[0]["author"] == "TEC-001"
    assert [x["kind"] for x in n.for_case(code, kinds=("trabajo", "cliente"))] == ["trabajo", "cliente"]
    assert n.for_case("C-999") == []


def test_notas_invalidas(repo):
    n = NotesRepository(repo)
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    for tipo, texto, caso in (("otro", "x", code), ("trabajo", "   ", code),
                              ("trabajo", "x" * 2001, code), ("trabajo", "x", "C-999")):
        with pytest.raises(ValueError):
            n.add(caso, tipo, texto)
    assert n.for_case(code) == []
    NotesRepository(repo)  # crear la tabla otra vez no falla


# ---------------- documento del cliente ----------------
def test_normalizar_documento():
    assert normalize_doc(" 4567-8912 ") == "45678912"
    assert normalize_doc("20.123.456.789") == "20123456789"
    assert normalize_doc("ce 00123") == "CE00123"
    assert normalize_doc("") == ""
    for malo in ("12345678901234567890X", "45%67", "45'67"):
        with pytest.raises(ValueError):
            normalize_doc(malo)


def test_migracion_de_la_columna_documento(tmp_path):
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)  # base anterior a la Parte C: clients sin doc_id
    con.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                "phone TEXT NOT NULL DEFAULT '')")
    con.execute("INSERT INTO clients(name, phone) VALUES ('Peña', '987')")
    con.commit()
    con.close()
    db = Database(ruta)
    try:
        fila = db.conn.execute("SELECT name, phone, doc_id FROM clients").fetchone()
        assert tuple(fila) == ("Peña", "987", "")
    finally:
        db.close()


def test_documento_por_caso(repo):
    cr = ClientsRepository(repo)
    code = repo.register_intake("Luis", "987", "SN-1", "Laptop", "Lento")
    assert cr.doc_for_case(code) == ""
    cr.set_doc_for_case(code, "4567 8912")
    assert cr.doc_for_case(code) == "45678912"
    cr.set_doc_for_case(code, "")  # vacío: no borra el anterior
    assert cr.doc_for_case(code) == "45678912"
    assert cr.find_by_doc("4567-8912")["name"] == "Luis"
    assert cr.find_by_doc("000") is None and cr.find_by_doc("%%") is None
    with pytest.raises(ValueError):
        cr.set_doc_for_case("C-999", "123")


# ---------------- búsqueda ----------------
def test_buscar_por_documento(repo):
    cr = ClientsRepository(repo)
    a = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    b = repo.register_intake("Ana", "2", "SN-2", "PC", "Lento")
    cr.set_doc_for_case(a, "45678912")
    cr.set_doc_for_case(b, "20123456789")
    q = SearchQueries(repo.c)
    assert _codigos(q.search_cases(text="45678912")) == [a]
    assert _codigos(q.search_cases(text="20123456")) == [b]
    rr = ReportsRepository(repo)
    rr.add(b, "cliente", "x.pdf")
    assert q.search_reports(text="20123456789")["total"] == 1


def test_buscar_por_marca_y_modelo_de_las_capturas(repo):
    hw = HardwareRepository(repo)
    a = repo.register_intake("Luis", "1", "SN-1", "Portátil de Luis", "Lento")
    b = repo.register_intake("Ana", "2", "SN-2", "PC de escritorio", "Lento")
    hw.save_capture(a, _scan())  # HP Laptop 15-dw
    c = repo.register_intake("Luis", "1", "SN-1", "Portátil de Luis", "Se calienta")  # sin captura propia
    q = SearchQueries(repo.c)
    assert sorted(_codigos(q.search_cases(text="15-dw"))) == sorted([a, c])  # cualquier captura del equipo
    assert sorted(_codigos(q.search_cases(text="HP 15-dw Luis"))) == sorted([a, c])
    assert b not in _codigos(q.search_cases(text="HP"))
    assert q.search_cases(text="Lenovo")["total"] == 0
    assert q.search_cases(text="%")["total"] == 0  # los comodines siguen siendo texto


def test_busqueda_en_base_con_datos(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        repo = Repository(db)
        repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
        assert SearchQueries(repo.c).search_cases(text="Luis")["total"] == 1
    finally:
        db.close()


# ---------------- inventario ----------------
def test_textos_del_inventario():
    filas = {(f["category"], f["label"]): f for f in inventory_rows(run_scan(env=_env()))}
    falta = filas[("Gráficos", "Memoria gráfica (WMI no la informa o supera los 4 GB)")]
    assert falta["value"] == "No disponible"  # sin "No disponible (No disponible)"
    assert "(según Windows Storage)" in filas[("Almacenamiento", "Unidad física 1")]["value"]
    assert filas[("Batería", "Capacidad de diseño")]["value"] == "50 000 mWh"


# ---------------- datos y contenido de los reportes ----------------
def _caso_con_historial(repo):
    hw = HardwareRepository(repo)
    c1 = repo.register_intake("Luis Peña", "987", "SN-1", "Laptop HP", "Lento")
    viejo = _scan("2026-09-25T10:00:00")
    viejo["inventory"]["memory"]["total_gb"] = 7.8
    hw.save_capture(c1, viejo)
    c2 = repo.register_intake("Luis Peña", "987", "SN-1", "Laptop HP", "Se calienta, se apaga solo")
    hw.save_capture(c2, _scan("2026-10-06T09:00:00", psutil=_psutil(bateria=False)))
    hw.save_capture(c2, _scan("2026-10-06T09:30:00"))  # la más reciente es la que se usa
    ClientsRepository(repo).set_doc_for_case(c2, "45678912")
    repo.save_diagnosis(c2, diagnose(repo.get_case(c2)["problem"], repo.get_scan(c2)))
    n = NotesRepository(repo)
    n.add(c2, "observacion", "NOTA-INTERNA disipador obstruido", "TEC-001")
    n.add(c2, "trabajo", "NOTA-TRABAJO limpieza interna", "TEC-001")
    n.add(c2, "cliente", "NOTA-CLIENTE use una mesa", "TEC-001")
    return c1, c2


def test_datos_del_reporte_salen_de_la_ultima_captura(repo):
    c1, c2 = _caso_con_historial(repo)
    d = load_report_data(repo, c2)
    assert d["capture"]["captured_at"] == "2026-10-06T09:30:00" and d["capture"]["count"] == 2
    assert d["doc_id"] == "45678912"
    titulos = [t for t, _f in d["categories"]]
    assert titulos[0] == "Identificación" and "Batería" in titulos  # la última captura sí tiene batería
    assert all(f["status"] != "ok" for f in d["unavailable"])
    assert d["previous"] == {"case_code": c1, "captured_at": "2026-09-25T10:00:00"}
    assert [c["area"] for c in d["changes"]] == ["Memoria RAM"]
    assert [n["kind"] for n in d["notes"]] == ["observacion", "trabajo", "cliente"]
    assert d["diag_saved"] is True


def test_reporte_de_escaneo_antiguo_y_sin_captura(repo):
    code = repo.register_intake("Ana", "1", "SN-2", "PC", "Lento")
    d = load_report_data(repo, code)
    assert d["scan"] is None and d["capture"] is None and d["categories"] == []
    assert d["previous"] is None and d["changes"] == []
    repo.save_scan(code, {"version": 1, "scanned_at": "2026-09-01T08:00:00", "summary": {}, "metrics": {},
                          "components": [{"name": "CPU", "detail": "i5", "status": "ok"},
                                         {"name": "Temperaturas", "detail": "No disponible", "status": "warn"}]})
    d = load_report_data(repo, code)
    assert d["capture"] is None and [t for t, _f in d["categories"]] == ["CPU"]
    assert [f["category"] for f in d["unavailable"]] == ["Temperaturas"]
    assert measured_items(d["scan"]) == [("CPU", "i5")]


def _textos(monkeypatch, repo, code, tipo):
    """Construye el reporte y devuelve el texto de todos sus párrafos."""
    capturado = {}

    def falso(story, path, titulo, autor, codigo):
        capturado["story"] = story

    monkeypatch.setattr(base, "_construir", falso)
    data = load_report_data(repo, code)
    (tecnico.build_technical if tipo == "tecnico" else cliente.build_client)(data, "x.pdf", "TEC-001")
    textos = []

    def recorrer(f):
        if hasattr(f, "getPlainText"):
            textos.append(f.getPlainText())
        for attr in ("_content", "_cellvalues"):
            for x in getattr(f, attr, []) or []:
                for y in (x if isinstance(x, (list, tuple)) else [x]):
                    recorrer(y)

    for f in capturado["story"]:
        recorrer(f)
    return "\n".join(textos)


def test_contenido_del_reporte_tecnico(monkeypatch, repo):
    _c1, c2 = _caso_con_historial(repo)
    t = _textos(monkeypatch, repo, c2, "tecnico")
    for esperado in ("Inventario de hardware", "Procesador", "Intel(R) Core(TM) i5-1135G7",
                     "Información no disponible", "Cambios desde la inspección anterior", "45678912",
                     "NOTA-INTERNA", "NOTA-TRABAJO", "NOTA-CLIENTE", "06/10/2026 09:30"):
        assert esperado in t, esperado


def test_contenido_del_reporte_para_el_cliente(monkeypatch, repo):
    _c1, c2 = _caso_con_historial(repo)
    t = _textos(monkeypatch, repo, c2, "cliente")
    for esperado in ("Lo que medimos", "Qué significa", "Cambios desde su visita anterior",
                     "NOTA-TRABAJO", "NOTA-CLIENTE", "no incluye precios ni plazos"):
        assert esperado in t, esperado
    assert "NOTA-INTERNA" not in t  # las observaciones técnicas no salen al cliente
    assert "UUID" not in t and "MAC" not in t  # sin datos técnicos internos
    assert "S/" not in t


def test_lo_que_medimos_y_temperatura_aproximada():
    items = dict(measured_items(_scan()))
    assert items["Memoria RAM"].startswith("16 GB") and items["Sistema operativo"] == "Windows 11 Pro"
    assert "aproximado" not in items["Temperatura"]
    s = _scan()
    s["inventory"]["sensors"]["cpu_temp_source"] = "ACPI"
    assert "aproximado" in dict(measured_items(s))["Temperatura"]
    assert measured_items(None) == [] and measured_items({}) == []


def test_implicaciones_para_el_cliente():
    assert "respaldar" in implication({"id": "R-007"})
    assert implication({"id": "R-999"}) == cliente.IMPLICACION_GENERICA


def test_pagina_x_de_n(monkeypatch, repo, tmp_path):
    _c1, c2 = _caso_con_historial(repo)
    escritos = []
    original = rl_canvas.Canvas.drawRightString

    def registrar(self, x, y, texto, *a, **k):
        escritos.append(texto)
        return original(self, x, y, texto, *a, **k)

    monkeypatch.setattr(rl_canvas.Canvas, "drawRightString", registrar)
    ruta = generate_report(repo, ReportsRepository(repo), c2, "tecnico", "TEC-001", out_dir=tmp_path)
    paginas = [e for e in escritos if e.startswith("Página ")]
    n = len(paginas)
    assert n >= 2 and paginas == [f"Página {i} de {n}" for i in range(1, n + 1)]
    with open(ruta, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_ambos_reportes_se_generan(repo, tmp_path):
    _c1, c2 = _caso_con_historial(repo)
    rr = ReportsRepository(repo)
    for tipo in ("tecnico", "cliente"):
        ruta = generate_report(repo, rr, c2, tipo, "TEC-001", out_dir=tmp_path)
        assert ruta.exists() and ruta.stat().st_size > 3000
    assert [r["kind"] for r in rr.for_case(c2)] == ["cliente", "tecnico"]
