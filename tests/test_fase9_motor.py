import time

import pytest

from app.diagnosis.engine import diagnose
from tests.validacion import CASOS, S_CPU, S_OK, evaluar


@pytest.mark.parametrize("cid,texto,scan,esperado", CASOS, ids=[c[0] for c in CASOS])
def test_caso_de_validacion(cid, texto, scan, esperado):
    ids = [c["id"] for c in diagnose(texto, scan)["causes"]]
    if esperado is None:
        assert ids == [], f"No debía proponer causas, propuso {ids}"
    else:
        assert ids and ids[0] == esperado, f"Esperado {esperado}, obtuvo {ids}"


def test_metricas_de_acierto():
    r = evaluar()
    assert r["total"] >= 20
    assert r["top1"] >= 0.9 and r["top3"] >= 0.95


def test_estados_generales():
    assert diagnose("Lento")["status"] == "DATOS INSUFICIENTES"
    assert diagnose("Equipo lento", S_OK)["status"] == "SIN HALLAZGOS RELEVANTES"
    assert diagnose("No enciende")["status"] == "ATENCIÓN REQUERIDA"
    assert diagnose("Pantalla con rayas")["status"] == "REVISIÓN RECOMENDADA"


def test_palabras_completas_no_subcadenas():
    # "ram" no debe coincidir dentro de "programas" ni de "derramó"
    for texto in ("Los programas se cierran", "Se derramó agua y se cierran las ventanas"):
        assert all(c["id"] != "R-004" for c in diagnose(texto, S_OK)["causes"])
    # pero sí como palabra o inicio de palabra
    assert any(c["id"] == "R-004" for c in diagnose("Poca ram, todo lento", None)["causes"])


def test_mediciones_solas_no_sugieren_malware():
    ids = [c["id"] for c in diagnose("Equipo lento", S_CPU)["causes"]]
    assert "R-013" not in ids


TEXTOS_EXTREMOS = [
    "", "   ", None, "ñandú 😀 \x00 <script>alert(1)</script>",
    "'; DROP TABLE cases;--", "LENTO " * 3000,
]


@pytest.mark.parametrize("texto", TEXTOS_EXTREMOS)
def test_entradas_extremas(texto):
    r = diagnose(texto, None)
    assert isinstance(r["causes"], list) and isinstance(r["status"], str)


SCANS_CORRUPTOS = [
    None, {}, "no es un diccionario", [1, 2, 3],
    {"metrics": "texto"}, {"metrics": [1, 2]}, {"summary": None},
    {"metrics": {"cpu_temp": "caliente", "cpu_usage": None, "ram_usage": True,
                 "disk_free_gb": [8], "disk_used_pct": float("nan")},
     "summary": {"ram": 16, "storage": None}},
    {"metrics": {"cpu_temp": "87"}},  # texto numérico: se interpreta como número
]


@pytest.mark.parametrize("scan", SCANS_CORRUPTOS)
def test_scans_corruptos(scan):
    r = diagnose("Se calienta, ventilador ruidoso", scan)
    assert isinstance(r["causes"], list) and r["disclaimer"]


def test_rendimiento():
    inicio = time.time()
    diagnose("equipo lento " * 1000, S_OK)
    assert time.time() - inicio < 3
