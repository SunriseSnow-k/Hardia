"""Validación del motor de reglas con casos conocidos.

Ejecutar el informe:  python -m tests.validacion
Cada caso tiene una causa principal esperada (o None si el sistema NO debe
proponer causas). Se mide el acierto de la causa principal (top-1) y si la
esperada aparece entre las 3 primeras (top-3).
"""
from app.diagnosis.engine import diagnose


def _scan(summary=None, **metricas):
    base = {"cpu_temp": 55, "cpu_usage": 20, "ram_usage": 40,
            "disk_free_gb": 200, "disk_used_pct": 30}
    base.update(metricas)
    resumen = {"ram": "16 GB", "storage": "SSD 512 GB"}
    resumen.update(summary or {})
    return {"summary": resumen, "metrics": base, "components": []}


S_OK = _scan()
S_CALOR = _scan(cpu_temp=87, cpu_usage=76, ram_usage=82, disk_free_gb=64, disk_used_pct=40)
S_REFRIG = _scan(cpu_temp=92, cpu_usage=18)
S_CPU = _scan(cpu_usage=95, cpu_temp=60)
S_RAM = _scan(ram_usage=92, cpu_usage=30)
S_POCA_RAM = _scan({"ram": "4 GB"}, ram_usage=60)
S_DISCO = _scan({"storage": "SSD 256 GB"}, disk_free_gb=8, disk_used_pct=96)
S_HDD = _scan({"ram": "8 GB", "storage": "HDD 500 GB"})

CASOS = [
    ("V01", "Se calienta mucho y el ventilador suena fuerte", S_CALOR, "R-001"),
    ("V02", "Equipo lento, tarda en abrir programas y se congela", S_CPU, "R-003"),
    ("V03", "Disco lleno", S_DISCO, "R-006"),
    ("V04", "Revisión general del equipo", S_DISCO, "R-006"),
    ("V05", "Se apaga solo, reinicios y pantalla azul", S_OK, "R-011"),
    ("V06", "No enciende, no prende", None, "R-010"),
    ("V07", "Pantalla azul después de actualizar Windows", None, "R-012"),
    ("V08", "Muchos anuncios y ventanas emergentes en el navegador", S_CPU, "R-013"),
    ("V09", "Pantalla con rayas y artefactos", None, "R-014"),
    ("V10", "El monitor no da imagen", None, "R-014"),
    ("V11", "Errores de almacenamiento y ruido de clics", None, "R-007"),
    ("V12", "Computadora lenta, tarda en iniciar", S_HDD, "R-008"),
    ("V13", "Computadora lenta, tarda en iniciar", S_OK, "R-009"),
    ("V14", "Poca memoria, equipo lento y se congela", S_POCA_RAM, "R-005"),
    ("V15", "Las aplicaciones se cierran solas y todo va lento", S_RAM, "R-004"),
    ("V16", "El ventilador gira pero la laptop se calienta y se apaga", S_REFRIG, "R-001"),
    ("V17", "Lento", None, None),
    ("V18", "Equipo lento", S_OK, None),
    ("V19", "", None, None),
    ("V20", "Los programas se cierran", S_OK, None),
    ("V21", "Mi hijo derramó café sobre el teclado", None, None),
]


def evaluar(casos=CASOS) -> dict:
    filas = []
    for cid, texto, scan, esperado in casos:
        ids = [c["id"] for c in diagnose(texto, scan)["causes"]]
        if esperado is None:
            top1 = top3 = not ids
        else:
            top1 = bool(ids) and ids[0] == esperado
            top3 = esperado in ids[:3]
        filas.append({"id": cid, "texto": texto, "esperado": esperado, "obtenidas": ids,
                      "top1": top1, "top3": top3})
    n = len(filas)
    return {"filas": filas, "total": n,
            "top1": sum(f["top1"] for f in filas) / n,
            "top3": sum(f["top3"] for f in filas) / n}


def main() -> None:
    r = evaluar()
    print(f'{"ID":<5}{"Esperado":<10}{"Obtenido (en orden)":<28}{"Top-1":<7}Caso')
    for f in r["filas"]:
        print(f'{f["id"]:<5}{str(f["esperado"] or "—"):<10}{", ".join(f["obtenidas"]) or "—":<28}'
              f'{"OK" if f["top1"] else "FALLA":<7}{f["texto"] or "(vacío)"}')
    print(f'\nCasos: {r["total"]} · Acierto top-1: {r["top1"]:.0%} · Acierto top-3: {r["top3"]:.0%}')


if __name__ == "__main__":
    main()