"""Colector portátil: escanea el PC del cliente y guarda el archivo .diag en el USB.

Empaquetado es Colector.exe (ver diagnostico.spec), que va en la carpeta Colector del USB y pide
permisos de administrador al abrirse (sin ellos no se leen temperaturas, ventiladores ni SMART).
No instala nada ni escribe en el PC del cliente: el archivo queda en la carpeta Resultados, junto
a Colector.exe (en el USB: <unidad>\\Colector\\Resultados).

Pasos: escaneo → resumen de salud → prueba de rendimiento opcional (CPU y lectura de discos, solo
lectura) → resumen final. El escaneo se guarda antes de la prueba: si se cancela, no se pierde.
El resumen es orientativo; la evaluación completa se ve en el taller al importar el archivo.

En desarrollo:  python -m app.hardware.cli [carpeta_destino] [--con-prueba | --sin-prueba] [--sin-pausa]
"""
import multiprocessing
import sys
from pathlib import Path

from app.hardware import diag_file, lhm
from app.hardware.scanner import LectorTemperatura, run_scan
from app.health import benchmark as bm
from app.health import evaluate, load_references
from app.health.evaluate import GRAVEDAD


def destino_predeterminado() -> Path:
    """Carpeta Resultados junto a Colector.exe (en desarrollo, dentro de la carpeta actual)."""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / diag_file.CARPETA_RESULTADOS


def ruta_libre(carpeta: Path, nombre: str) -> Path:
    """No sobrescribe un escaneo anterior del mismo equipo y día: agrega -2, -3…"""
    ruta = carpeta / nombre
    n = 2
    while ruta.exists():
        ruta = carpeta / f"{Path(nombre).stem}-{n}{Path(nombre).suffix}"
        n += 1
    return ruta


# ---------------- resumen de salud ----------------
def resumen_salud(data: dict, prueba: dict | None = None) -> list[str]:
    """Líneas de texto con el índice de salud y el estado de cada componente, peores primero."""
    try:
        refs = load_references()
    except ValueError:
        return ["No se pudo cargar la base de referencias: la salud se evaluará en el taller."]
    r = evaluate(data, refs, prueba)
    if not r["componentes"]:
        return [r.get("aviso") or "Sin datos de salud."]
    ind = r["indice"]
    lineas = [f'Índice de salud: {ind["valor"]:.0f} % ({ind["estado"]})' if ind["valor"] is not None
              else "Índice de salud: sin datos suficientes para calcularlo"]
    for c in sorted(r["componentes"], key=lambda c: GRAVEDAD[c["estado"]]):
        detalle = c["resumen"] or c["medido"]["valor"]
        pct = f' · {c["pct"]:.0f} % de fábrica' if c["pct"] is not None else ""
        lineas.append(f'  [{c["estado"]}] {c["nombre"]}: {detalle}{pct}')
    return lineas


def _imprimir(titulo: str, lineas: list[str]) -> None:
    print(f"\n{titulo}\n" + "-" * len(titulo))
    for linea in lineas:
        print(linea)


# ---------------- prueba de rendimiento ----------------
def _interactivo() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def quiere_prueba(argv: list[str], discos: list[dict]) -> bool:
    if "--con-prueba" in argv:
        return True
    if "--sin-prueba" in argv or not _interactivo():
        return False
    minutos = max(1, round(bm.duracion_estimada(discos) / 60))
    print(f"\nLa prueba de rendimiento mide el procesador y la velocidad de lectura de los discos "
          f"(unos {minutos} min). Solo lee: no modifica archivos del cliente. Conviene tener el "
          "cargador conectado y los programas cerrados.")
    return input("¿Ejecutar la prueba de rendimiento? [s/N]: ").strip().lower() in ("s", "si", "sí")


def ejecutar_prueba(discos: list[dict], lector=LectorTemperatura, **kw) -> dict | None:
    """Ejecuta la prueba mostrando el avance. Devuelve None si se canceló (Ctrl+C)."""
    ultimo = [-10.0]

    def muestra(t, ops_s, temp, _fuente):
        if t - ultimo[0] >= 10:
            ultimo[0] = t
            grados = f" · {temp:.0f} °C" if temp is not None else ""
            print(f"    {t:4.0f} s · {ops_s:,.0f} operaciones/s{grados}")

    try:
        with lector() as lt:
            res = bm.ejecutar(discos, al_paso=lambda _i, texto: print(f"  {texto}…"), al_muestrear=muestra,
                              leer_temp=lt.leer, **kw)
    except KeyboardInterrupt:
        print("\nPrueba cancelada. El escaneo ya quedó guardado.")
        return None
    if res["cpu"] and res["cpu"].get("detenido_por_temp"):
        print(f"  La prueba se detuvo: la CPU llegó a {bm.CORTE_TEMP:.0f} °C (corte de seguridad).")
    for d in res["discos"]:
        if d.get("estado") != "ok":
            print(f'  Disco {d.get("model") or d.get("index")}: no se midió ({d.get("motivo")}).')
    return None if res["cancelado"] else res


# ---------------- programa ----------------
def main(argv: list[str]) -> int:
    for flujo in (sys.stdout, sys.stderr):  # una consola con otra página de códigos no debe romper el escaneo
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")
    args = [a for a in argv[1:] if not a.startswith("--")]
    pausa = getattr(sys, "frozen", False) and "--sin-pausa" not in argv
    try:
        destino = Path(args[0]) if args else destino_predeterminado()
        print("Colector de diagnóstico — escaneo de este equipo\n")
        if not lhm.es_administrador():
            print("AVISO: sin permisos de administrador no se leerán temperaturas, ventiladores "
                  "ni el estado SMART completo, y la prueba no podrá medir los discos.\n")
        data = run_scan(lambda _i, n, d, s: print(f"  [{s}] {n}: {d}"))
        ruta = diag_file.save_scan(data, ruta_libre(destino, diag_file.default_filename(data)))
        print(f"\nEscaneo guardado en: {ruta}")
        _imprimir("Salud del equipo (orientativa)", resumen_salud(data))

        discos = bm.discos_de(data)
        if quiere_prueba(argv, discos):
            print("\nPrueba de rendimiento (Ctrl+C para cancelar)")
            prueba = ejecutar_prueba(discos)
            if prueba:
                data["benchmark"] = prueba
                diag_file.save_scan(data, ruta)
                _imprimir("Salud del equipo con la prueba de rendimiento", resumen_salud(data, prueba))
                print(f"\nPrueba guardada en: {ruta}")

        print(f"\nListo. El archivo está en la carpeta: {ruta.parent}")
        print("Lleve el USB al taller (o envíe ese archivo) e impórtelo en Escanear → Importar desde USB.")
        codigo = 0
    except Exception as e:  # el técnico debe ver el motivo, no una ventana que se cierra
        print(f"\nNo se pudo completar el escaneo: {e}")
        codigo = 1
    if pausa:
        input("\nPresione Enter para salir…")
    return codigo


if __name__ == "__main__":
    multiprocessing.freeze_support()  # la prueba de CPU usa procesos: necesario en Colector.exe
    sys.exit(main(sys.argv))
