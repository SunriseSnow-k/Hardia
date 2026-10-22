"""Lleva los colectores portátiles de un sistema a otro para que cada instalador incluya los dos.

PyInstaller no compila para otro sistema: el colector de Windows se genera en Windows y el de Linux en
Linux. Cada build (build.ps1, build.sh) deja el suyo empaquetado en
dist/colectores/Colector-<sistema>.tar.gz. Si se copian esos archivos a dist/colectores del equipo que
arma el instalador (o los trae la integración continua: .github/workflows/paquetes.yml), el build los
incluye en el programa, en Colectores/<sistema>, y desde Escanear se preparan memorias con los dos.

Los enlaces simbólicos se guardan como archivos: así se pueden extraer en Windows y copiar a
memorias FAT32.

Uso:  python tools/colectores.py empaquetar <sistema> <carpeta del colector>
      python tools/colectores.py incluir <sistema del programa> <carpeta del programa>
"""
import shutil
import sys
import tarfile
from pathlib import Path

SISTEMAS = ("windows", "linux")
NOMBRES = {"windows": "Windows", "linux": "Linux"}
PROGRAMA = {"windows": "Colector.exe", "linux": "Colector"}
CARPETA = Path(__file__).resolve().parents[1] / "dist" / "colectores"


def archivo(sistema: str, carpeta: Path = CARPETA) -> Path:
    return carpeta / f"Colector-{sistema}.tar.gz"


def empaquetar(sistema: str, colector: Path, carpeta: Path = CARPETA) -> Path:
    """Guarda el colector generado en este equipo (sin escaneos) para llevarlo a los otros sistemas."""
    if not (colector / PROGRAMA[sistema]).is_file():
        raise SystemExit(f"No se encontró el colector de {NOMBRES[sistema]} en {colector}.")
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = archivo(sistema, carpeta)
    with tarfile.open(destino, "w:gz", dereference=True) as t:
        for ruta in sorted(colector.iterdir()):
            if ruta.name != "Resultados":
                t.add(ruta, arcname=ruta.name)
    return destino


def incluir(propio: str, programa: Path, carpeta: Path = CARPETA) -> list[str]:
    """Extrae en <programa>/Colectores/<sistema> el colector del otro sistema si está en
    `carpeta`. Devuelve los sistemas incluidos."""
    incluidos = []
    for sistema in SISTEMAS:
        origen, destino = archivo(sistema, carpeta), programa / "Colectores" / sistema
        shutil.rmtree(destino, ignore_errors=True)
        if sistema == propio:
            continue  # el del propio sistema va en Colector
        if not origen.is_file():
            print(f"  Aviso: falta {origen.name}: el programa no podrá preparar el colector de {NOMBRES[sistema]} "
                  f"(genérelo con el build en {NOMBRES[sistema]} y copie el archivo a {carpeta}).")
            continue
        destino.mkdir(parents=True)
        with tarfile.open(origen, "r:gz") as t:
            t.extractall(destino, filter="data")  # rechaza rutas absolutas o que salgan de la carpeta
        if not (destino / PROGRAMA[sistema]).is_file():
            shutil.rmtree(destino)
            raise SystemExit(f"{origen.name} no contiene el colector de {NOMBRES[sistema]}.")
        incluidos.append(sistema)
        print(f"  Colector de {NOMBRES[sistema]} incluido.")
    return incluidos


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in ("empaquetar", "incluir") or argv[2] not in SISTEMAS:
        print(__doc__)
        return 2
    if argv[1] == "empaquetar":
        print(f"  Colector para los otros sistemas: {empaquetar(argv[2], Path(argv[3]))}")
    else:
        incluir(argv[2], Path(argv[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
