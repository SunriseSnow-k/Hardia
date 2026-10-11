"""Escaneo por línea de comandos para llevar los datos de otro PC en un USB.
Uso:  python -m app.hardware.cli E:\\
"""
import sys
from pathlib import Path

from . import diag_file
from .scanner import run_scan


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        destino = Path(argv[1])
    else:
        unidades = diag_file.removable_drives()
        destino = unidades[0] if unidades else Path.cwd()
    print("Escaneando este equipo…")
    data = run_scan(lambda i, n, d, s: print(f"  [{s}] {n}: {d}"))
    ruta = diag_file.save_scan(data, destino / diag_file.default_filename(data))
    print(f"\nEscaneo guardado en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))