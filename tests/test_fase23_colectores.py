"""Fase 23: cada instalador lleva los colectores de Windows y Linux, así desde el programa de
cualquiera de los dos se prepara una memoria con ambos (tools/colectores.py los lleva de un sistema a
otro; colector_usb los encuentra en Colectores/<sistema>)."""
import importlib.util
import sys
import tarfile
from pathlib import Path

import pytest

from app.hardware import colector_usb, diag_file
from app.plataforma import SISTEMA

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("colectores", RAIZ / "tools" / "colectores.py")
colectores = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(colectores)

OTRO = next(s for s in colector_usb.SISTEMAS if s != SISTEMA)


def _colector(carpeta: Path, sistema: str) -> Path:
    (carpeta / "_internal").mkdir(parents=True)
    (carpeta / ("Colector.exe" if sistema == "windows" else "Colector")).write_bytes(b"MZ" + b"0" * 100)
    (carpeta / "_internal" / "lib").write_bytes(b"lib")
    (carpeta / "Resultados").mkdir()
    (carpeta / "Resultados" / "DEL_TALLER.diag").write_text("{}")
    return carpeta


@pytest.fixture
def dos(tmp_path):
    return {s: _colector(tmp_path / "build" / s / "Colector", s) for s in colector_usb.SISTEMAS}


# ---------------- tools/colectores.py ----------------
def test_empaquetar_e_incluir_el_colector_del_otro_sistema(tmp_path, dos, capsys):
    dist = tmp_path / "dist" / "colectores"
    colectores.empaquetar("linux", dos["linux"], dist)
    with tarfile.open(colectores.archivo("linux", dist)) as t:
        assert "Resultados" not in {Path(n).parts[0] for n in t.getnames()}  # nunca escaneos del taller
    programa = tmp_path / "SistemaDiagnostico"
    (programa / "Colectores" / "linux" / "viejo").mkdir(parents=True)  # de una versión anterior
    assert colectores.incluir("windows", programa, dist) == ["linux"]
    assert sorted(p.name for p in (programa / "Colectores").iterdir()) == ["linux"]
    assert sorted(p.name for p in (programa / "Colectores" / "linux").iterdir()) == ["Colector", "_internal"]
    # sin el archivo del otro sistema solo avisa: el instalador se genera igual
    assert colectores.incluir("linux", programa, dist) == []
    assert "falta Colector-windows.tar.gz" in capsys.readouterr().out
    assert not (programa / "Colectores" / "windows").exists() and not (programa / "Colectores" / "linux").exists()


def test_archivos_de_colector_invalidos(tmp_path, dos):
    with pytest.raises(SystemExit):
        colectores.empaquetar("windows", dos["linux"], tmp_path)  # no hay Colector.exe
    dist = tmp_path / "dist"
    dist.mkdir()
    with tarfile.open(colectores.archivo("linux", dist), "w:gz") as t:
        t.add(dos["linux"] / "_internal", arcname="_internal")  # sin el programa
    with pytest.raises(SystemExit):
        colectores.incluir("windows", tmp_path / "prog", dist)
    assert not (tmp_path / "prog" / "Colectores" / "linux").exists()
    assert colectores.main(["colectores.py", "otra-cosa"]) == 2


# ---------------- el programa encuentra los dos ----------------
def test_programa_instalado_encuentra_los_colectores_de_los_otros_sistemas(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SistemaDiagnostico" / "SistemaDiagnostico"))
    base = tmp_path / "SistemaDiagnostico"
    assert colector_usb.origen() == base / "Colector"
    assert colector_usb.origen(OTRO) == base / "Colectores" / OTRO
    assert colector_usb.disponibles() == []
    _colector(base / "Colector", SISTEMA)
    assert colector_usb.disponibles() == [SISTEMA]
    _colector(base / "Colectores" / OTRO, OTRO)
    assert colector_usb.disponibles() == [SISTEMA, OTRO]  # el de este sistema primero


def _instalacion(monkeypatch, dos, cuales=colector_usb.SISTEMAS):
    monkeypatch.setattr(colector_usb, "origen",
                        lambda sistema=SISTEMA: dos[sistema] if sistema in cuales else Path("/no-existe"))


def test_preparar_los_dos_colectores_desde_un_solo_programa(monkeypatch, tmp_path, dos):
    _instalacion(monkeypatch, dos)
    usb = tmp_path / "usb"
    usb.mkdir()
    listos = colector_usb.preparar_varios(usb)
    assert list(listos) == [SISTEMA, OTRO]
    c = usb / "Colector"
    assert {s: p.relative_to(c).as_posix() for s, p in listos.items()} == {
        "windows": "Colector.exe", "linux": "colector.sh"}
    assert sorted(p.name for p in c.iterdir()) == ["Colector.exe", "Resultados", "_internal", "colector.sh", "linux"]
    assert list((c / "Resultados").iterdir()) == []  # los escaneos del taller no se copian
    texto = (usb / colector_usb.INSTRUCCIONES).read_text(encoding="utf-8-sig")
    assert all(n in texto for n in ("Colector.exe", "colector.sh"))


def test_sin_espacio_para_todos_no_copia_ninguno(monkeypatch, tmp_path, dos):
    from collections import namedtuple
    _instalacion(monkeypatch, dos)
    usb = tmp_path / "usb"
    usb.mkdir()
    uso = namedtuple("uso", "total used free")
    monkeypatch.setattr(colector_usb.shutil, "disk_usage", lambda _p: uso(10 ** 9, 10 ** 9, 150))
    with pytest.raises(OSError, match="Windows, Linux|espacio suficiente"):
        colector_usb.preparar_varios(usb, list(colector_usb.SISTEMAS))
    assert list(usb.iterdir()) == []


# ---------------- interfaz ----------------
@pytest.fixture
def pagina():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.pages.escaneo import EscaneoPage
    return EscaneoPage()


def test_boton_prepara_todos_o_uno(pagina, monkeypatch, tmp_path, dos):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    _instalacion(monkeypatch, dos)
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(diag_file, "removable_drives", lambda: [usb])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    preguntas = []

    def elegir(respuesta):
        def get_item(_padre, _titulo, _texto, opciones, *_a, **_k):
            preguntas.append(opciones)
            return (respuesta(opciones), True)
        return staticmethod(get_item)

    monkeypatch.setattr(QInputDialog, "getItem", elegir(lambda o: "Solo Linux"))
    pagina._preparar_usb()
    assert preguntas[0][0] == "Todos: " + ", ".join(colector_usb.NOMBRES[s] for s in [SISTEMA, OTRO])
    assert (usb / "Colector" / "linux").is_dir() and not (usb / "Colector" / "Colector.exe").exists()
    assert "Colector-Linux.com" in pagina.msg.text()

    monkeypatch.setattr(QInputDialog, "getItem", elegir(lambda o: o[0]))
    pagina._preparar_usb()
    assert "USB listo (" in pagina.msg.text() and "con Windows" in pagina.msg.text()
    assert all((usb / "Colector" / n).exists() for n in ("Colector.exe", "colector.sh"))

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    pagina.msg.setText("")
    pagina._preparar_usb()  # cancelado: no hace nada
    assert pagina.msg.text() == ""


def test_con_un_solo_colector_no_pregunta_cual(pagina, monkeypatch, tmp_path, dos):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    _instalacion(monkeypatch, dos, cuales=(SISTEMA,))
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(diag_file, "removable_drives", lambda: [usb])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: pytest.fail("no debe preguntar")))
    pagina._preparar_usb()
    assert "USB listo" in pagina.msg.text()
    assert (usb / "Colector" / colector_usb.PARA_EJECUTAR[SISTEMA]).exists()
