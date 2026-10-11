import json

import pytest

from app.hardware import diag_file
from app.hardware.scanner import run_scan, COMPONENT_NAMES


def _ejemplo():
    return {
        "format": "SD-DIAG", "version": 1, "scanned_at": "2026-10-06T10:42:00", "host": "PC",
        "summary": {"description": "Laptop HP", "serial": "SN-48213", "cpu": "i5",
                    "ram": "16 GB", "storage": "SSD 512 GB", "os": "Windows 11"},
        "components": [{"name": "CPU", "detail": "i5", "status": "ok"}],
        "metrics": {},
    }


def test_guardar_y_cargar(tmp_path):
    ruta = diag_file.save_scan(_ejemplo(), tmp_path / "a.diag")
    assert diag_file.load_scan(ruta)["summary"]["serial"] == "SN-48213"


def test_archivo_invalido(tmp_path):
    p = tmp_path / "x.diag"
    p.write_text("esto no es json", encoding="utf-8")
    with pytest.raises(ValueError):
        diag_file.load_scan(p)
    p.write_text(json.dumps({"format": "otro"}), encoding="utf-8")
    with pytest.raises(ValueError):
        diag_file.load_scan(p)


def test_nombre_de_archivo():
    d = _ejemplo()
    d["summary"]["serial"] = "SN 48/213"
    assert diag_file.default_filename(d) == "SN_48_213_2026-10-06.diag"


def test_run_scan_estructura():
    data = run_scan()
    assert [c["name"] for c in data["components"]] == COMPONENT_NAMES
    assert all(c["status"] in ("ok", "warn", "error") for c in data["components"])
    assert data["summary"]["description"]
    assert data["format"] == "SD-DIAG"