"""Fase 18: colector portátil en USB (Colector.exe o Colector en Linux) y preparación de la memoria desde el programa."""
import sys
from collections import namedtuple

import pytest

from app.hardware import cli, colector_usb, diag_file
from app.paths import VAR_DATOS
from app.plataforma import ES_WINDOWS, SISTEMA

# Lo que el técnico ejecuta en el PC del cliente: Colector.exe en Windows, colector.sh en Linux
PARA_EJECUTAR = colector_usb.PARA_EJECUTAR[SISTEMA]
# Dónde queda el programa del colector en la memoria (el de Linux va en Colector/linux)
PROGRAMA = {"windows": ("Colector", "Colector.exe"),
            "linux": ("Colector", "linux", "Colector-Linux.com")}[SISTEMA]

ESCANEO = {"format": diag_file.FORMAT, "version": diag_file.VERSION, "scanned_at": "2026-10-15T10:00:00",
           "host": "PC-CLIENTE", "summary": {"serial": "ABC 123"}, "components": [], "metrics": {}}


@pytest.fixture
def escaneo_simulado(monkeypatch):
    def run_scan(progreso):
        progreso(0, "CPU", "Intel", "ok")
        return dict(ESCANEO)
    monkeypatch.setattr(cli, "run_scan", run_scan)
    monkeypatch.setattr(cli.lhm, "es_administrador", lambda: False)


# ---------------- Colector (cli) ----------------
def test_colector_guarda_sin_sobrescribir(tmp_path, escaneo_simulado, capsys):
    assert cli.main(["Colector.exe", str(tmp_path), "--sin-pausa"]) == 0
    assert cli.main(["Colector.exe", str(tmp_path), "--sin-pausa"]) == 0
    archivos = sorted(p.name for p in tmp_path.glob("*.diag"))
    assert archivos == ["ABC_123_2026-10-15-2.diag", "ABC_123_2026-10-15.diag"]
    assert diag_file.load_scan(tmp_path / archivos[1])["host"] == "PC-CLIENTE"
    salida = capsys.readouterr().out
    assert "administrador" in salida and "[ok] CPU: Intel" in salida and "Listo" in salida


def test_colector_informa_el_error_y_espera_enter(tmp_path, monkeypatch, capsys):
    def falla(_progreso):
        raise RuntimeError("WMI dañado")
    monkeypatch.setattr(cli, "run_scan", falla)
    monkeypatch.setattr(cli.lhm, "es_administrador", lambda: True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli, "_interactivo", lambda: True)  # abierto en una consola
    esperas = []
    monkeypatch.setattr("builtins.input", lambda texto: esperas.append(texto))
    assert cli.main(["Colector.exe", str(tmp_path)]) == 1
    assert "WMI dañado" in capsys.readouterr().out and len(esperas) == 1  # la ventana no se cierra sola


def test_destino_es_la_carpeta_resultados_del_colector(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "E" / "Colector" / colector_usb.EXE))
    assert cli.destino_predeterminado() == tmp_path / "E" / "Colector" / "Resultados"
    monkeypatch.setattr(sys, "frozen", False)
    monkeypatch.chdir(tmp_path)
    assert cli.destino_predeterminado() == tmp_path / "Resultados"


def test_colector_crea_resultados_y_guarda_ahi(tmp_path, escaneo_simulado, monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Colector" / "Colector.exe"))
    monkeypatch.setattr("builtins.input", lambda _t: "")
    assert cli.main(["Colector.exe"]) == 0
    assert [p.name for p in (tmp_path / "Colector" / "Resultados").iterdir()] == ["ABC_123_2026-10-15.diag"]
    assert str(tmp_path / "Colector" / "Resultados") in capsys.readouterr().out


def test_taller_encuentra_los_escaneos_del_colector(tmp_path, monkeypatch):
    import os
    resultados = tmp_path / "Colector" / "Resultados"
    resultados.mkdir(parents=True)
    viejo = diag_file.save_scan(ESCANEO, tmp_path / "VIEJO.diag")  # versiones anteriores: en la raíz
    nuevo = diag_file.save_scan(ESCANEO, resultados / "NUEVO.diag")
    os.utime(viejo, (1, 1))
    monkeypatch.setattr(diag_file, "removable_drives", lambda: [tmp_path])
    assert diag_file.find_usb_scans() == [nuevo, viejo]  # los más recientes primero


# ---------------- Preparar el USB ----------------
def _colector(carpeta, windows: bool):
    (carpeta / "_internal").mkdir(parents=True)
    (carpeta / ("Colector.exe" if windows else "Colector")).write_bytes(b"MZ" + b"0" * 100)
    (carpeta / "_internal" / ("lhm.dll" if windows else "libpython.so")).write_bytes(b"lib")
    return carpeta


@pytest.fixture
def fuente(tmp_path):
    return _colector(tmp_path / "programa" / "Colector", ES_WINDOWS)


def test_preparar_copia_y_reemplaza_version_anterior(tmp_path, fuente):
    usb = tmp_path / "usb"
    (usb / "Colector").mkdir(parents=True)
    (usb / "EQUIPO_2026-10-01.diag").write_text("{}")
    colector_usb.preparar(usb, fuente)
    (usb / "Colector" / ("_internal" if ES_WINDOWS else "linux/_internal") / "viejo.txt").write_text("anterior")
    exe = colector_usb.preparar(usb, fuente)
    assert exe == usb / "Colector" / PARA_EJECUTAR
    assert usb.joinpath(*PROGRAMA).read_bytes().startswith(b"MZ")
    assert not list(usb.rglob("viejo.txt")) and not (usb / "Colector.nuevo").exists()
    assert (usb / "EQUIPO_2026-10-01.diag").exists()  # los escaneos de la memoria no se tocan
    assert (usb / "Colector" / "Resultados").is_dir()


def test_una_memoria_lleva_los_dos_colectores(tmp_path):
    """Cada sistema reemplaza solo su colector: el de Windows y el de Linux conviven en la memoria."""
    win, lin = _colector(tmp_path / "w" / "Colector", True), _colector(tmp_path / "l" / "Colector", False)
    usb = tmp_path / "usb"
    (usb / "Colector" / "Resultados").mkdir(parents=True)
    (usb / "Colector" / "Resultados" / "CLIENTE.diag").write_text("{}")
    assert colector_usb.preparar(usb, win, sistema="windows") == usb / "Colector" / "Colector.exe"
    assert colector_usb.preparar(usb, lin, sistema="linux") == usb / "Colector" / "colector.sh"
    colector_usb.preparar(usb, win, sistema="windows")  # actualizar el de Windows no borra el de Linux
    c = usb / "Colector"
    assert sorted(p.name for p in c.iterdir()) == ["Colector.exe", "Resultados", "_internal", "colector.sh", "linux"]
    assert (c / "_internal" / "lhm.dll").exists() and (c / "linux" / "_internal" / "libpython.so").exists()
    assert [p.name for p in (c / "Resultados").iterdir()] == ["CLIENTE.diag"]
    texto = (usb / colector_usb.INSTRUCCIONES).read_text(encoding="utf-8-sig")
    assert "Colector.exe" in texto and "sh colector.sh" in texto


def test_linux_pasa_la_version_anterior_a_su_carpeta(tmp_path):
    """La versión anterior dejaba el colector de Linux suelto en Colector: se reemplaza por Colector/linux."""
    lin = _colector(tmp_path / "l" / "Colector", False)
    usb = tmp_path / "usb"
    _colector(usb / "Colector", False)
    (usb / "Colector" / "glibc-minima.txt").write_text("2.39")
    colector_usb.preparar(usb, lin, sistema="linux")
    assert sorted(p.name for p in (usb / "Colector").iterdir()) == ["Resultados", "colector.sh", "linux"]


def test_preparar_conserva_resultados_y_no_copia_escaneos_del_taller(tmp_path, fuente):
    (fuente / "Resultados").mkdir()
    (fuente / "Resultados" / "DEL_TALLER.diag").write_text("{}")
    usb = tmp_path / "usb"
    (usb / "Colector" / "Resultados").mkdir(parents=True)
    (usb / "Colector" / "Resultados" / "CLIENTE.diag").write_text("{}")
    colector_usb.preparar(usb, fuente)
    assert [p.name for p in (usb / "Colector" / "Resultados").iterdir()] == ["CLIENTE.diag"]
    assert PARA_EJECUTAR in (usb / colector_usb.INSTRUCCIONES).read_text(encoding="utf-8-sig")


def test_preparar_valida_origen_unidad_y_espacio(tmp_path, fuente, monkeypatch):
    with pytest.raises(FileNotFoundError, match="no está incluido"):
        colector_usb.preparar(tmp_path, tmp_path / "no-existe")
    with pytest.raises(OSError, match="No se encuentra"):
        colector_usb.preparar(tmp_path / "Z", fuente)
    Uso = namedtuple("Uso", "total used free")
    monkeypatch.setattr(colector_usb.shutil, "disk_usage", lambda _u: Uso(100, 100, 10))
    with pytest.raises(OSError, match="espacio"):
        colector_usb.preparar(tmp_path, fuente)


def test_origen_empaquetado(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SistemaDiagnostico" / "SistemaDiagnostico.exe"))
    assert colector_usb.origen() == tmp_path / "SistemaDiagnostico" / "Colector"


@pytest.mark.skipif(ES_WINDOWS, reason="el lanzador colector.sh es solo de Linux")
def test_preparar_en_linux_deja_el_lanzador(tmp_path, fuente):
    usb = tmp_path / "usb"
    usb.mkdir()
    lanzador = colector_usb.preparar(usb, fuente, sistema="linux")
    texto = lanzador.read_text(encoding="utf-8")
    assert lanzador.name == "colector.sh" and texto.startswith("#!/bin/sh") and "\r" not in texto
    assert "sudo" in texto and '"$DIR/Resultados"' in texto


# ---------------- Interfaz ----------------
@pytest.fixture
def pagina(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.pages.escaneo import MVCD_EscaneoPage
    return MVCD_EscaneoPage()


def test_boton_preparar_usb(pagina, fuente, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(colector_usb, "origen", lambda sistema=SISTEMA: fuente if sistema == SISTEMA else fuente / "otro")
    monkeypatch.setattr(diag_file, "removable_drives", lambda: [])
    pagina._preparar_usb()
    assert "Conecte una memoria USB" in pagina.msg.text()

    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(diag_file, "removable_drives", lambda: [usb])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    pagina._preparar_usb()
    assert "USB listo" in pagina.msg.text() and usb.joinpath(*PROGRAMA).exists()


def test_boton_preparar_usb_elige_unidad_o_avisa(pagina, fuente, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(colector_usb, "origen", lambda sistema=SISTEMA: tmp_path / "sin-colector")
    pagina._preparar_usb()
    assert "no está incluido" in pagina.msg.text()

    monkeypatch.setattr(colector_usb, "origen", lambda sistema=SISTEMA: fuente if sistema == SISTEMA else fuente / "otro")
    e, f = tmp_path / "E", tmp_path / "F"
    e.mkdir()
    f.mkdir()
    monkeypatch.setattr(diag_file, "removable_drives", lambda: [e, f])
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (str(f), True)))
    pagina._preparar_usb()
    assert f.joinpath(*PROGRAMA).exists() and not (e / "Colector").exists()


# ---------------- Resumen de salud y prueba de rendimiento en el colector ----------------
RESULTADO = {"componentes": [
    {"estado": "Buen estado", "nombre": "Memoria", "resumen": "", "medido": {"valor": "3200 MT/s"}, "pct": 100.0},
    {"estado": "Atención", "nombre": "Batería", "resumen": "La batería perdió 55 % de su capacidad.",
     "medido": {"valor": "45 %"}, "pct": 45.0},
    {"estado": "Sin referencia", "nombre": "GPU", "resumen": "", "medido": {"valor": "No disponible"}, "pct": None},
], "indice": {"valor": 72.5, "estado": "Revisar"}, "aviso": ""}


def test_resumen_salud_ordena_por_gravedad(monkeypatch):
    vistos = []
    monkeypatch.setattr(cli, "evaluate", lambda scan, refs, prueba: vistos.append(prueba) or RESULTADO)
    lineas = cli.resumen_salud({}, {"cpu": {}})
    assert lineas[0] == "Índice de salud: 72 % (Revisar)"
    assert lineas[1] == "  [Atención] Batería: La batería perdió 55 % de su capacidad. · 45 % de fábrica"
    assert lineas[2].startswith("  [Buen estado] Memoria: 3200 MT/s") and "GPU: No disponible" in lineas[3]
    assert vistos == [{"cpu": {}}]  # la prueba se usa en la evaluación


def test_resumen_salud_sin_datos_o_sin_referencias(monkeypatch):
    assert "inventario" in cli.resumen_salud({"format": "SD-DIAG"})[0]  # evaluación real, sin inventario
    sin_indice = {**RESULTADO, "indice": {"valor": None, "estado": "Sin referencia"}}
    monkeypatch.setattr(cli, "evaluate", lambda *a: sin_indice)
    assert "sin datos suficientes" in cli.resumen_salud({})[0]

    def rota():
        raise ValueError("dañada")
    monkeypatch.setattr(cli, "load_references", rota)
    assert "en el taller" in cli.resumen_salud({})[0]


def test_quiere_prueba(monkeypatch):
    assert cli.quiere_prueba(["x", "--con-prueba"], []) is True
    assert cli.quiere_prueba(["x", "--sin-prueba"], []) is False
    assert cli.quiere_prueba(["x"], []) is False  # sin consola (pruebas, tareas automáticas): no pregunta
    monkeypatch.setattr(cli, "_interactivo", lambda: True)
    respuestas = iter(["S", ""])
    monkeypatch.setattr("builtins.input", lambda _t: next(respuestas))
    assert cli.quiere_prueba(["x"], [{"index": 0}]) is True
    assert cli.quiere_prueba(["x"], []) is False  # Enter = no


class _Lector:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @staticmethod
    def leer():
        return 60.0, "LHM"


def test_ejecutar_prueba_muestra_avance_y_avisos(monkeypatch, capsys):
    def ejecutar(discos, al_paso, al_muestrear, leer_temp, **kw):
        al_paso(0, "Procesador: carga de todos los núcleos")
        for t in (1, 5, 11):
            al_muestrear(t, 1500.0, leer_temp()[0], "LHM")
        return {"cpu": {"detenido_por_temp": True}, "cancelado": False,
                "discos": [{"index": 0, "model": "SSD X", "estado": "no_autorizado", "motivo": "requiere administrador"}]}
    monkeypatch.setattr(cli.bm, "ejecutar", ejecutar)
    res = cli.ejecutar_prueba([{"index": 0}], lector=_Lector)
    salida = capsys.readouterr().out
    assert res is not None and "Procesador: carga de todos los núcleos…" in salida
    assert salida.count("operaciones/s") == 2 and "60 °C" in salida  # una muestra cada 10 s
    assert "corte de seguridad" in salida and "SSD X: no se midió (requiere administrador)" in salida


def test_ejecutar_prueba_cancelada(monkeypatch, capsys):
    monkeypatch.setattr(cli.bm, "ejecutar", lambda *a, **k: {"cpu": {}, "discos": [], "cancelado": True})
    assert cli.ejecutar_prueba([], lector=_Lector) is None

    def interrumpe(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.bm, "ejecutar", interrumpe)
    assert cli.ejecutar_prueba([], lector=_Lector) is None
    assert "ya quedó guardado" in capsys.readouterr().out


def test_colector_con_prueba_la_guarda_en_el_diag(tmp_path, escaneo_simulado, monkeypatch, capsys):
    prueba = {"version": 1, "cpu": {"ops_s": 1500.0}, "discos": [], "cancelado": False}
    monkeypatch.setattr(cli, "ejecutar_prueba", lambda discos: prueba)
    assert cli.main(["Colector.exe", str(tmp_path), "--con-prueba"]) == 0
    archivos = list(tmp_path.glob("*.diag"))
    assert len(archivos) == 1 and diag_file.load_scan(archivos[0])["benchmark"] == prueba
    salida = capsys.readouterr().out
    assert "Salud del equipo (orientativa)" in salida and "con la prueba de rendimiento" in salida


def test_colector_prueba_cancelada_conserva_el_escaneo(tmp_path, escaneo_simulado, monkeypatch):
    monkeypatch.setattr(cli, "ejecutar_prueba", lambda discos: None)
    assert cli.main(["Colector.exe", str(tmp_path), "--con-prueba"]) == 0
    assert "benchmark" not in diag_file.load_scan(next(tmp_path.glob("*.diag")))


def test_diag_rechaza_prueba_danada(tmp_path):
    ruta = diag_file.save_scan({**ESCANEO, "benchmark": [1, 2]}, tmp_path / "x.diag")
    with pytest.raises(ValueError, match="dañado"):
        diag_file.load_scan(ruta)


# ---------------- Importación en el taller ----------------
def test_importar_diag_con_prueba_la_vincula_a_la_captura(tmp_path, monkeypatch):
    from app.db.database import QAKM_Database
    from app.db.hardware_repo import QAKM_HardwareRepository
    from app.db.health_repo import QAKM_HealthRepository
    from app.db.repo import QAKM_Repository
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))
    db = QAKM_Database(tmp_path / "t.db")
    try:
        repo = QAKM_Repository(db)
        code = repo.register_intake("Ana", "", "ABC123", "Laptop", "Lenta")
        prueba = {"version": 1, "fecha": "2026-10-15T10:05:00", "cpu": {"ops_s": 1500.0}, "discos": []}
        res = QAKM_HardwareRepository(repo).save_capture(code, {**ESCANEO, "benchmark": prueba})
        assert res["benchmark_id"] is not None
        cap = QAKM_HardwareRepository(repo).get_capture(res["capture_id"])
        assert "benchmark" not in cap["payload"]  # la prueba se guarda aparte, una sola vez
        bid, guardada = QAKM_HealthRepository(repo).latest_benchmark(code, res["capture_id"])
        assert bid == res["benchmark_id"] and guardada == prueba
        assert QAKM_HealthRepository(repo).evaluate_case(code)["benchmark_id"] == bid
        sin = QAKM_HardwareRepository(repo).save_capture(code, dict(ESCANEO))
        assert sin["benchmark_id"] is None
    finally:
        db.close()


# ---------------- doble clic en Linux ----------------
def test_en_la_memoria_el_colector_de_linux_termina_en_com(tmp_path):
    """FAT32 solo deja ejecutar .exe, .com y .bat: con .com se abre con doble clic."""
    lin = _colector(tmp_path / "l" / "Colector", False)
    usb = tmp_path / "usb"
    usb.mkdir()
    colector_usb.preparar(usb, lin, sistema="linux")
    assert sorted(p.name for p in (usb / "Colector" / "linux").iterdir()) == ["Colector-Linux.com", "_internal"]
    texto = (usb / "Colector" / "colector.sh").read_text(encoding="utf-8")
    assert '"$BIN/Colector-Linux.com"' in texto and 'EXE="$BIN/Colector"' in texto  # también la versión anterior
    assert "Colector-Linux.com" in (usb / colector_usb.INSTRUCCIONES).read_text(encoding="utf-8-sig")


def test_resultados_del_colector_de_linux_van_a_la_carpeta_comun(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Colector" / "linux" / "Colector-Linux.com"))
    assert cli.destino_predeterminado() == tmp_path / "Colector" / "Resultados"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Colector" / "Colector.exe"))
    assert cli.destino_predeterminado() == tmp_path / "Colector" / "Resultados"


def test_orden_para_abrir_una_terminal():
    hay = {"/usr/bin/x-terminal-emulator": "/usr/bin/cosmic-term", "/usr/bin/konsole": "/usr/bin/konsole",
           "/usr/bin/xterm": "/usr/bin/xterm"}

    def which(n):
        return next((r for r in hay if r.endswith("/" + n)), None)
    real = hay.get
    assert cli.orden_en_terminal(["sh", "c.sh"], "COSMIC", which, real) == \
        ["/usr/bin/x-terminal-emulator", "--", "sh", "c.sh"]
    assert cli.orden_en_terminal(["sh", "c.sh"], "KDE", which, real) == ["/usr/bin/konsole", "-e", "sh", "c.sh"]
    del hay["/usr/bin/x-terminal-emulator"], hay["/usr/bin/konsole"]
    assert cli.orden_en_terminal(["sh", "c.sh"], "GNOME", which, real) == ["/usr/bin/xterm", "-e", "sh", "c.sh"]
    hay.clear()
    assert cli.orden_en_terminal(["sh"], "", which, real) is None


def test_doble_clic_abre_el_colector_en_una_terminal(monkeypatch, tmp_path):
    exe = tmp_path / "Colector" / "linux" / "Colector-Linux.com"
    exe.parent.mkdir(parents=True)
    (tmp_path / "Colector" / "colector.sh").write_text("#!/bin/sh")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(cli, "_interactivo", lambda: False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("DIAG_COLECTOR_EN_TERMINAL", raising=False)
    monkeypatch.setattr(cli, "orden_en_terminal", lambda orden, _e: ["terminal", "--", *orden])
    abiertas = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda orden, **k: abiertas.append((orden, k["env"])))
    assert cli.main([str(exe)]) == 0
    assert abiertas[0][0] == ["terminal", "--", "sh", str(tmp_path / "Colector" / "colector.sh")]
    assert abiertas[0][1]["DIAG_COLECTOR_EN_TERMINAL"] == "1"
    monkeypatch.setenv("DIAG_COLECTOR_EN_TERMINAL", "1")  # ya está en la terminal: no abre otra
    assert not cli.relanzar_en_terminal([str(exe)])
