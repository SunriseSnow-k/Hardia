import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.ai.ollama_client import OllamaError
from app.db.database import QAKM_Database
from app.db.repo import QAKM_Repository
from app.paths import VAR_DATOS


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    """Datos en una carpeta temporal y Ollama simulado como no disponible."""
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))

    def sin_ollama(*args, **kwargs):
        raise OllamaError("sin ollama")

    monkeypatch.setattr("app.ai.config.list_models", sin_ollama)
    monkeypatch.setattr("app.ui.pages.ia_local.list_models", sin_ollama)


@pytest.fixture
def repo(tmp_path, qapp):
    db = QAKM_Database(tmp_path / "ui.db")
    r = QAKM_Repository(db)
    r.set_setting("auto_backup", "0")
    yield r
    db.close()


def _caso(repo):
    code = repo.register_intake("Luis Paredes", "987", "SN-48213", "Laptop HP",
                                "Se calienta, ventilador ruidoso")
    repo.save_scan(code, {
        "scanned_at": "2026-10-06T10:42:00",
        "summary": {"ram": "16 GB", "storage": "SSD 512 GB"},
        "components": [{"name": "CPU", "detail": "i5", "status": "ok"}],
        "metrics": {"cpu_temp": 87, "cpu_usage": 76},
    })
    return code


def test_navegacion_completa(repo):
    from app.ui.main_window import SECCIONES, MVCD_MainWindow
    _caso(repo)
    win = MVCD_MainWindow(repo, "TEC-001")
    for i in range(len(SECCIONES)):
        win.sidebar.setCurrentRow(i)
        assert win.pages.currentIndex() == i


def test_recepcion_guarda_y_avisa_reingreso(repo):
    from app.ui.pages.recepcion import MVCD_RecepcionPage
    page = MVCD_RecepcionPage(repo)
    page.cliente.setText("Ana Torres")
    page.telefono.setText("111")
    page.equipo.setText("PC Dell")
    page.serie.setText("SN-77")
    page.problema.setText("Se apaga solo")
    page.chips[0].setChecked(True)
    page._guardar()
    casos = repo.list_cases()
    assert len(casos) == 1
    assert "Lento" in casos[0]["problem"] and "Se apaga solo" in casos[0]["problem"]
    assert page.ok.text().startswith("Caso C-001")
    page.serie.setText("sn-77")  # mismo equipo, otra escritura: reingreso
    assert not page.alert.isHidden()
    assert "SN-77" in page.alert_text.text()


def test_dialogos_de_caso_y_diagnostico(repo):
    from app.ui.case_dialog import MVCD_CaseDialog
    from app.ui.diagnosis_dialog import MVCD_DiagnosisDialog
    code = _caso(repo)
    MVCD_CaseDialog(repo, code)
    dlg = MVCD_DiagnosisDialog(repo, code)
    assert dlg.result["causes"] and dlg.result["causes"][0]["priority"] == "Alta"
    dlg._guardar()
    assert dlg.saved and repo.get_diagnosis(code) is not None
    dlg.done(0)


def test_listados(repo):
    from app.ui.pages.equipos import MVCD_EquiposPage
    from app.ui.pages.historial import MVCD_HistorialPage
    from app.ui.pages.reportes import MVCD_ReportesPage
    _caso(repo)
    assert MVCD_HistorialPage(repo).tabla.rowCount() == 1
    assert MVCD_EquiposPage(repo).tabla.rowCount() == 1
    assert MVCD_ReportesPage(repo, "TEC-001").combo.count() == 1


def test_configuracion_negocio(repo):
    from app.ui.pages.configuracion import MVCD_ConfiguracionPage
    repo.create_user("TEC-001", "secreto1")  # la primera cuenta es administrador
    page = MVCD_ConfiguracionPage(repo, "TEC-001")
    page.nombre.setText("Taller X")
    page._guardar_negocio()
    assert repo.get_setting("business_name") == "Taller X"
    page.nombre.setText("")
    page._guardar_negocio()
    assert repo.get_setting("business_name") == "Taller X"
    assert "Escriba" in page.msg_neg.text()


def test_asistente_bienvenida(repo):
    from app.ui.welcome import MVCD_WelcomeDialog
    dlg = MVCD_WelcomeDialog(repo)
    dlg.nombre.setText("Taller X")
    dlg._ir(1)
    dlg._guardar()
    assert repo.get_setting("business_name") == "Taller X"
    assert repo.get_setting("setup_done") == "1"
