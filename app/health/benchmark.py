"""Prueba de rendimiento (sin Qt).

- CPU: carga de todos los núcleos durante unos 60 s con procesos (multiprocessing). Se mide
  cuántas unidades de trabajo fijas se completan por segundo y cuánto se mantiene el ritmo.
  Se detiene sola si la temperatura llega al corte de seguridad (95 °C).
- Discos: lectura secuencial de la unidad física (\\\\.\\PhysicalDriveN en Windows; /dev/sdX o
  /dev/nvmeXnY en Linux) durante unos 30 s, SOLO LECTURA y sin abrir archivos: no toca los datos
  del cliente. Exige administrador (root en Linux); sin él la medición queda como "No disponible".
- Condiciones: cargador conectado, carga de batería, uso previo de CPU y programas abiertos.

El puntaje de CPU está en unidades propias de este programa: solo es comparable con
referencias medidas con esta misma prueba.
"""
import ctypes
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime
from statistics import mean
from typing import Any

import psutil

VERSION = 1
DURACION_CPU = 60
DURACION_DISCO = 30
CORTE_TEMP = 95.0
VENTANA = 10  # segundos para el ritmo inicial y final
BLOQUE = 1024 * 1024  # 1 MiB (múltiplo del tamaño de sector, requerido sin caché)

def discos_de(scan: dict) -> list[dict]:
    """Discos internos de una captura que la prueba puede leer: [{index, model, device}]
    (device solo existe en las capturas de Linux: /dev/sda)."""
    sto = ((scan or {}).get("inventory") or {}).get("storage") or {}
    return [{"index": u.get("index"), "model": u.get("model"), "device": u.get("device")}
            for u in sto.get("physical") or []
            if isinstance(u, dict) and not u.get("external") and u.get("index") is not None]


def duracion_estimada(discos: list[dict], duracion_cpu: float = DURACION_CPU,
                      duracion_disco: float = DURACION_DISCO) -> float:
    return duracion_cpu + duracion_disco * len(discos)


# ---------------- CPU ----------------
def _unidad_de_trabajo() -> int:
    """Cálculo fijo y determinista (enteros), igual en todas las ejecuciones."""
    s = 0
    for i in range(3000):
        s = (s + i * i) % 1_000_003
    return s


def _trabajador(contador, parar, fin: float):
    """Proceso hijo: repite la unidad de trabajo y suma al contador compartido."""
    local, ultimo = 0, time.time()
    while not parar.is_set() and time.time() < fin:
        _unidad_de_trabajo()
        local += 1
        ahora = time.time()
        if ahora - ultimo >= 0.2:
            with contador.get_lock():
                contador.value += local
            local, ultimo = 0, ahora
    with contador.get_lock():
        contador.value += local


def prueba_cpu(duracion: float = DURACION_CPU, procesos: int | None = None, cancelado=lambda: False,
               leer_temp=None, al_muestrear=None, corte: float = CORTE_TEMP) -> dict:
    """Carga todos los núcleos. `leer_temp()` -> (°C | None, fuente | None);
    `al_muestrear(t, ops_s, temp, fuente)` se llama cada segundo."""
    n = max(1, procesos or os.cpu_count() or 1)
    ctx = mp.get_context("spawn")
    contador, parar = ctx.Value("q", 0), ctx.Event()
    hijos = [ctx.Process(target=_trabajador, args=(contador, parar, time.time() + duracion + 30), daemon=True)
             for _ in range(n)]
    muestras, temps, fuente = [], [], None
    detenido = cancelada = False
    try:
        for h in hijos:
            h.start()
        limite = time.time() + 20  # arranque de los procesos
        while contador.value == 0 and time.time() < limite and not cancelado():
            time.sleep(0.05)
        t0 = time.perf_counter()
        previo, t_previo = contador.value, t0
        while True:
            time.sleep(1.0)
            ahora = time.perf_counter()
            actual = contador.value
            ritmo = (actual - previo) / max(ahora - t_previo, 1e-6)
            previo, t_previo = actual, ahora
            temp, f = leer_temp() if leer_temp else (None, None)
            if temp is not None:
                temps.append(float(temp))
                fuente = f or fuente
            t = ahora - t0
            muestras.append({"t": round(t, 1), "ops_s": round(ritmo, 1),
                             "temp": None if temp is None else round(float(temp), 1)})
            if al_muestrear:
                al_muestrear(t, ritmo, temp, f)
            if temp is not None and float(temp) >= corte:
                detenido = True
                break
            if cancelado():
                cancelada = True
                break
            if t >= duracion:
                break
        total, transcurrido = contador.value, time.perf_counter() - t0
    finally:
        parar.set()
        for h in hijos:
            h.join(3)
            if h.is_alive():
                h.terminate()
    ritmos = [m["ops_s"] for m in muestras]
    ventana = max(1, min(VENTANA, len(ritmos) // 3 or 1))
    inicial = mean(ritmos[:ventana]) if ritmos else 0.0
    final = mean(ritmos[-ventana:]) if ritmos else 0.0
    return {
        "ops_s": round(total / transcurrido, 1) if transcurrido > 0 else 0.0,
        "inicial_ops_s": round(inicial, 1), "final_ops_s": round(final, 1),
        "sostenido_pct": round(100 * final / inicial, 1) if inicial else None,
        "duracion_s": round(transcurrido, 1), "procesos": n,
        "temp_max": max(temps) if temps else None, "temp_fuente": fuente,
        "detenido_por_temp": detenido, "cancelado": cancelada, "muestras": muestras,
    }


# ---------------- Discos (solo lectura, sin caché) ----------------
GENERIC_READ = 0x80000000
FILE_SHARE_READ_WRITE = 0x1 | 0x2
OPEN_EXISTING = 3
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
MEM_COMMIT_RESERVE, MEM_RELEASE, PAGE_READWRITE = 0x3000, 0x8000, 0x04
ERROR_ACCESS_DENIED = 5


def _kernel32():
    if sys.platform != "win32":  # pragma: no cover (comparación literal: así la entiende mypy)
        raise OSError("solo Windows")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    from ctypes import wintypes as w
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
    k.ReadFile.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    k.VirtualAlloc.argtypes = [w.LPVOID, ctypes.c_size_t, w.DWORD, w.DWORD]
    k.VirtualAlloc.restype = w.LPVOID
    k.VirtualFree.argtypes = [w.LPVOID, ctypes.c_size_t, w.DWORD]
    return k


def lectura_disco(indice, duracion: float = DURACION_DISCO, cancelado=lambda: False,
                  al_avanzar=None, ruta: str | None = None, sesion=None) -> dict:
    """Lee secuencialmente la unidad física `indice` (o `ruta`, usado en las pruebas) sin caché.
    Nunca escribe. Devuelve {index, lectura_mb_s, bytes, duracion_s, estado, motivo}."""
    base = {"index": indice, "lectura_mb_s": None, "bytes": 0, "duracion_s": 0.0, "estado": "ok", "motivo": ""}
    if sys.platform != "win32":
        if not ruta:
            return {**base, "estado": "no_disponible", "motivo": "no se conoce el dispositivo de la unidad"}
        return _lectura_linux(base, ruta, duracion, cancelado, al_avanzar, sesion)
    ruta = ruta or rf"\\.\PhysicalDrive{int(indice)}"
    k = _kernel32()
    h = k.CreateFileW(ruta, GENERIC_READ, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING,
                      FILE_FLAG_NO_BUFFERING | FILE_FLAG_SEQUENTIAL_SCAN, None)
    if h is None or h == ctypes.c_void_p(-1).value:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            return {**base, "estado": "no_autorizado",
                    "motivo": "requiere ejecutar el programa como administrador"}
        return {**base, "estado": "fallo", "motivo": f"Windows no permitió abrir la unidad (error {err})"}
    buf = k.VirtualAlloc(None, BLOQUE, MEM_COMMIT_RESERVE, PAGE_READWRITE)  # alineado a página
    from ctypes import wintypes as w
    leidos, total = w.DWORD(0), 0
    t0 = time.perf_counter()
    cancelada = False
    try:
        if not buf:
            return {**base, "estado": "fallo", "motivo": "no se pudo reservar memoria para la lectura"}
        ultimo_aviso = t0
        while True:
            if not k.ReadFile(h, buf, BLOQUE, ctypes.byref(leidos), None) or leidos.value == 0:
                break  # fin de la unidad o error de lectura: se usa lo leído
            total += leidos.value
            ahora = time.perf_counter()
            if al_avanzar and ahora - ultimo_aviso >= 0.5:
                al_avanzar(ahora - t0, total)
                ultimo_aviso = ahora
            if ahora - t0 >= duracion:
                break
            if cancelado():
                cancelada = True
                break
    finally:
        if buf:
            k.VirtualFree(buf, 0, MEM_RELEASE)
        k.CloseHandle(h)
    dur = time.perf_counter() - t0
    if total == 0:
        return {**base, "estado": "fallo", "motivo": "no se pudo leer la unidad", "duracion_s": round(dur, 1)}
    return {**base, "lectura_mb_s": round(total / 1e6 / max(dur, 1e-6), 1), "bytes": total,
            "duracion_s": round(dur, 1), "cancelado": cancelada}


def _lectura_linux(base: dict, ruta: str, duracion: float, cancelado, al_avanzar, sesion=None) -> dict:
    """Lectura secuencial sin caché (O_DIRECT) de un dispositivo de bloque en Linux. Sin root, la
    hace el ayudante con permisos de la `sesion` (ver app/hardware/permisos_linux.py), si se abrió."""
    if sesion is not None and not os.access(ruta, os.R_OK):
        return {**base, **sesion.leer_disco(ruta, duracion, cancelado, al_avanzar)}
    from app.hardware.ayudante_root import leer_dispositivo
    r = leer_dispositivo(ruta, duracion, cancelado, al_avanzar)
    if r["estado"] == "no_autorizado":
        r["motivo"] = "requiere permisos de administrador (en Linux se piden al iniciar la prueba)"
    return {**base, **r}


# ---------------- condiciones ----------------
def condiciones(ps=psutil, max_programas: int = 5) -> dict:
    """Condiciones en que se hace la prueba (afectan al resultado)."""
    try:
        b = ps.sensors_battery()
    except Exception:
        b = None
    try:
        uso = ps.cpu_percent(interval=0.5)
    except Exception:
        uso = None
    programas = []
    try:
        procesos = list(ps.process_iter(["name", "memory_info"]))
        total = len(procesos)
        grandes = sorted((p for p in procesos if p.info.get("memory_info") and p.info.get("name")),
                         key=lambda p: p.info["memory_info"].rss, reverse=True)
        for p in grandes:
            nombre = p.info["name"]
            if nombre not in programas and nombre.lower() not in ("system", "registry", "memory compression"):
                programas.append(nombre)
            if len(programas) >= max_programas:
                break
    except Exception:
        total = None
    return {"cargador": None if b is None else bool(b.power_plugged),
            "bateria_pct": None if b is None else b.percent,
            "uso_cpu_previo": uso, "procesos": total, "programas_mas_memoria": programas,
            "fecha": datetime.now().isoformat(timespec="seconds")}


def texto_condiciones(c: dict) -> list[tuple[str, str]]:
    c = c if isinstance(c, dict) else {}
    cargador = {True: "Conectado", False: "No conectado (en batería)", None: "Sin batería / no informado"}
    filas = [("Cargador", cargador.get(c.get("cargador"), "No informado"))]
    if c.get("bateria_pct") is not None:
        filas.append(("Carga de la batería", f'{c["bateria_pct"]:.0f} %'))
    if c.get("uso_cpu_previo") is not None:
        filas.append(("Uso de CPU antes de la prueba", f'{c["uso_cpu_previo"]:.0f} %'))
    if c.get("procesos") is not None:
        filas.append(("Procesos en ejecución", str(c["procesos"])))
    if c.get("programas_mas_memoria"):
        filas.append(("Programas con más memoria", ", ".join(c["programas_mas_memoria"])))
    return filas


# ---------------- ejecución completa ----------------
def ejecutar(discos: list[dict], cancelado=lambda: False, al_paso=None, al_muestrear=None,
             al_avanzar_disco=None, leer_temp=None, duracion_cpu: float = DURACION_CPU,
             duracion_disco: float = DURACION_DISCO, procesos: int | None = None,
             cond: dict | None = None, sesion=None) -> dict:
    """CPU y luego cada disco. `discos`: [{index, model}] de la captura del caso. `sesion`: ayudante
    con permisos de Linux que lee los discos cuando el programa no es root."""
    res: dict[str, Any] = {"version": VERSION, "fecha": datetime.now().isoformat(timespec="seconds"),
           "condiciones": cond if cond is not None else condiciones(),
           "cpu": None, "discos": [], "cancelado": False,
           "parametros": {"duracion_cpu_s": duracion_cpu, "duracion_disco_s": duracion_disco,
                          "corte_temp_c": CORTE_TEMP}}
    if al_paso:
        al_paso(0, "Procesador: carga de todos los núcleos")
    res["cpu"] = prueba_cpu(duracion_cpu, procesos, cancelado, leer_temp, al_muestrear)
    if res["cpu"]["cancelado"] or cancelado():
        res["cancelado"] = True
        return res
    for i, d in enumerate(discos, 1):
        if al_paso:
            al_paso(i, f'Disco {d.get("model") or d.get("index")}: lectura secuencial (solo lectura)')
        r = lectura_disco(d.get("index"), duracion_disco, cancelado,
                          (lambda t, b, i=i: al_avanzar_disco(i, t, b)) if al_avanzar_disco else None,
                          ruta=d.get("device") if os.name != "nt" else None, sesion=sesion)
        r["model"] = d.get("model")
        res["discos"].append(r)
        if r.get("cancelado") or cancelado():
            res["cancelado"] = True
            return res
    return res
