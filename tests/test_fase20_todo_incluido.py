"""Fase 20: el instalador trae todo lo necesario (el controlador de sensores PawnIO incluido);
solo el paquete de IA se sigue descargando aparte."""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from app.hardware import lhm

RAIZ = Path(__file__).resolve().parents[1]
PAWNIO_SHA = "1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032"
solo_windows = pytest.mark.skipif(sys.platform != "win32", reason="PawnIO es un controlador de Windows")


def test_el_proyecto_trae_el_instalador_oficial_de_pawnio():
    setup = RAIZ / "redist" / lhm.PAWNIO_SETUP
    assert hashlib.sha256(setup.read_bytes()).hexdigest() == PAWNIO_SHA


def test_el_instalador_incluye_pawnio_y_lo_instala_si_falta():
    iss = (RAIZ / "installer.iss").read_text(encoding="utf-8-sig")
    assert r'Source: "redist\PawnIO_setup.exe"; DestDir: "{app}\Controladores"' in iss
    assert '"-install -silent"' in iss and "Check: not PawnIOInstalado" in iss
    assert "MinVersion=10.0.17134" in iss  # Windows con .NET Framework 4.7.2 (LibreHardwareMonitor)
    licencias = (RAIZ / "app" / "assets" / "LICENCIAS_TERCEROS.txt").read_text(encoding="utf-8")
    assert "PawnIO" in licencias and "GPL-2.0" in licencias


@solo_windows
def test_ubicacion_del_instalador_de_pawnio(monkeypatch, tmp_path):
    assert lhm.instalador_pawnio() == RAIZ / "redist" / lhm.PAWNIO_SETUP  # en desarrollo
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SistemaDiagnostico.exe"))
    assert lhm.instalador_pawnio() is None  # instalación sin el controlador
    (tmp_path / "Controladores").mkdir()
    (tmp_path / "Controladores" / lhm.PAWNIO_SETUP).write_bytes(b"MZ")
    assert lhm.instalador_pawnio() == tmp_path / "Controladores" / lhm.PAWNIO_SETUP


@solo_windows
def test_requisitos_ofrecen_el_controlador_incluido(monkeypatch):
    monkeypatch.setattr(lhm, "es_administrador", lambda: True)
    monkeypatch.setattr(lhm, "pawnio_instalado", lambda: False)
    assert any("botón «Instalar controlador»" in f for f in lhm.requisitos_sensores())
    monkeypatch.setattr(lhm, "instalador_pawnio", lambda: None)
    assert any("pawnio.eu" in f for f in lhm.requisitos_sensores())


@solo_windows
def test_instalar_pawnio_eleva_y_espera(monkeypatch):
    ordenes = []
    estado = {"instalado": False}

    def run(args, **kw):
        ordenes.append(args)
        estado["instalado"] = True
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(lhm, "pawnio_instalado", lambda: estado["instalado"])
    assert lhm.instalar_pawnio() is True
    orden = ordenes[0][-1]
    assert "-Verb RunAs" in orden and "-Wait" in orden and "'-install','-silent'" in orden

    estado["instalado"] = False
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("sin powershell")))
    assert lhm.instalar_pawnio() is False
    monkeypatch.setattr(lhm, "instalador_pawnio", lambda: None)
    assert lhm.instalar_pawnio() is False


@solo_windows
def test_boton_instalar_controlador(monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton
    QApplication.instance() or QApplication([])
    from app.ui.pages.escaneo import MVCD_EscaneoPage
    estado = {"instalado": False}
    monkeypatch.setattr(lhm, "pawnio_instalado", lambda: estado["instalado"])
    monkeypatch.setattr(lhm, "es_administrador", lambda: True)
    pagina = MVCD_EscaneoPage()
    botones = [b for b in pagina.aviso_sensores.findChildren(QPushButton) if b.text() == "Instalar controlador"]
    assert len(botones) == 1 and not pagina.aviso_sensores.isHidden()

    monkeypatch.setattr(lhm, "instalar_pawnio", lambda: False)
    botones[0].click()
    assert "No se instaló" in pagina.msg.text()

    def instala():
        estado["instalado"] = True
        return True
    monkeypatch.setattr(lhm, "instalar_pawnio", instala)
    botones[0].click()
    assert "Controlador instalado" in pagina.msg.text()
    assert not [b for b in pagina.aviso_sensores.findChildren(QPushButton) if b.text() == "Instalar controlador"]
