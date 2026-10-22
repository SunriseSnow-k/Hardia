"""Lectura de hardware: en Windows con psutil + WMI + LibreHardwareMonitorLib; en Linux con
psutil + /sys + /proc (ver linux.py).

Cada categoría es independiente: si una falla, el resto sigue funcionando. Solo se
registran datos verificables; lo que no se pudo obtener se guarda con su motivo:
no disponible, no aplica, sin permisos o fallo de detección.
"""
import contextlib
import gc
import logging
import platform
import socket
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psutil

from app.plataforma import ES_WINDOWS

from . import lhm
from . import linux as _linux
from .colectores import _FUNCIONES
from .comun import _res, clasificar_error
from .diag_file import FORMAT, VERSION
from .inventory import FALLO, NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK
from .sensores import _leer_lhm

log = logging.getLogger(__name__)

try:
    import wmi
except Exception:  # pragma: no cover
    wmi = None
try:
    import pythoncom
except Exception:  # pragma: no cover
    pythoncom = None


COLECTORES_NOMBRES = [
    ("Identificación", "identity"), ("CPU", "cpu"), ("RAM", "memory"),
    ("Almacenamiento", "storage"), ("GPU", "graphics"), ("Placa base / BIOS", "motherboard"),
    ("Sistema operativo", "os"), ("Red", "network"), ("Batería", "battery"),
    ("Otros dispositivos", "other"), ("Temperaturas", "sensors"),
]


COMPONENT_NAMES = [n for n, _ in COLECTORES_NOMBRES]


class _Entorno:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Acceso al sistema. Las pruebas lo sustituyen por uno simulado."""

    def __init__(self, c, ns):
        self.c, self._ns, self.psutil = c, ns, psutil
        self.lector = None  # lhm.Lector abierto, para lecturas repetidas

    def ns(self, nombre):
        if self._ns is None:
            raise RuntimeError("WMI no disponible")
        return self._ns(nombre)

    @staticmethod
    def hostname():
        return socket.gethostname()

    @staticmethod
    def machine():
        return platform.machine()

    @staticmethod
    def processor():
        return platform.processor() or "Procesador"

    def lhm(self):
        return self.lector.leer() if self.lector is not None else lhm.leer_sensores()

    @staticmethod
    def es_admin():
        return lhm.es_administrador()

    @staticmethod
    def pawnio():
        return lhm.pawnio_instalado()


def _crear_entorno():
    if not ES_WINDOWS:
        return _linux.EntornoLinux()
    c: Any = None
    ns: Callable[[str], Any] | None = None
    if wmi:
        try:
            c = wmi.WMI()

            def ns(nombre):
                return wmi.WMI(namespace=nombre)
        except Exception:
            c = ns = None
    return _Entorno(c, ns)


def _es_linux(env) -> bool:
    return getattr(env, "sistema", "windows") == "linux"


def _funciones(env) -> dict:
    """Colectores del sistema del entorno (los entornos simulados de las pruebas son de Windows)."""
    return _linux.FUNCIONES if _es_linux(env) else _FUNCIONES


_ESTADO_COMPONENTE = {OK: "ok", NO_COMPATIBLE: "ok", NO_DISPONIBLE: "warn",
                      NO_AUTORIZADO: "warn", FALLO: "error"}


def _escanear(progress, env) -> dict:
    """Lee todas las categorías. Los objetos WMI viven solo dentro de esta función."""
    comps: list[dict] = []
    metricas: dict[str, Any] = {}
    inventario: dict[str, Any] = {}
    disp: dict[str, Any] = {}
    resumen = {"description": "", "serial": "", "cpu": "", "ram": "", "storage": "", "os": "", "gpu": ""}
    # una sola lectura de sensores, compartida por los colectores
    env._lhm_cache = _linux.leer_sensores(env) if _es_linux(env) else _leer_lhm(env)
    try:
        _recorrer(progress, env, comps, metricas, inventario, disp, resumen)
    finally:
        env._lhm_cache = None
    if not resumen["description"]:
        resumen["description"] = env.hostname()
    return {"format": FORMAT, "version": VERSION,
            "scanned_at": datetime.now().isoformat(timespec="seconds"),
            "host": env.hostname(), "summary": resumen, "components": comps, "metrics": metricas,
            "inventory": inventario, "availability": disp}


def _recorrer(progress, env, comps, metricas, inventario, disp, resumen):
    for i, (nombre, clave) in enumerate(COLECTORES_NOMBRES):
        try:
            r = _funciones(env)[clave](env)
        except Exception as e:
            r = _res(clasificar_error(e), f"No se pudo leer ({type(e).__name__})")
        estado = _ESTADO_COMPONENTE.get(r["status"], "error")
        if r["alert"] and estado == "ok":
            estado = "warn"
        detalle = r["detail"] + (" · datos parciales" if r["status"] == OK and r["faltantes"] else "")
        if r["status"] == OK:
            inventario[clave] = r["data"]
        disp[clave] = {"status": r["status"], "detail": r["detail"], "faltantes": r["faltantes"]}
        resumen.update({k: v for k, v in r["summary"].items() if v})
        metricas.update(r["metrics"])
        comps.append({"name": nombre, "detail": detalle, "status": estado})
        if progress:
            progress(i, nombre, detalle, estado)


def read_cpu_temperature(env=None) -> tuple[float | None, str | None]:
    """Temperatura máxima de la CPU en este momento y su fuente (para la prueba de rendimiento).
    Devuelve (None, None) si no hay lectura. Nunca lanza."""
    def leer(e):
        try:
            r = _funciones(e)["sensors"](e)
        except Exception:
            return None, None
        if r["status"] != OK:
            return None, None
        return r["metrics"].get("cpu_temp"), r["data"].get("cpu_temp_source")

    if env is not None:
        return leer(env)
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        return leer(_crear_entorno())
    finally:
        gc.collect()
        if pythoncom:
            pythoncom.CoUninitialize()


class LectorTemperatura:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Lecturas repetidas de temperatura desde un hilo: abre WMI y LibreHardwareMonitor una sola vez.
    Uso: with LectorTemperatura() as lt: temp, fuente = lt.leer()"""

    def __init__(self, env=None):
        self._env_dado = env
        self.env = env

    def __enter__(self):
        if self._env_dado is None:
            if pythoncom:
                pythoncom.CoInitialize()
            self.env = _crear_entorno()
            if _es_linux(self.env):
                return self  # hwmon se lee en cada llamada: no hay nada que mantener abierto
            try:
                self.env.lector = lhm.Lector().__enter__()
            except Exception:
                self.env.lector = None  # sin biblioteca: WMI de LHM o ACPI
        return self

    def leer(self) -> tuple[float | None, str | None]:
        return read_cpu_temperature(self.env)

    def __exit__(self, *exc):
        if self._env_dado is None:
            if self.env is not None and self.env.lector is not None:
                with contextlib.suppress(Exception):
                    self.env.lector.__exit__(None, None, None)
            self.env = None
            gc.collect()
            if pythoncom:
                pythoncom.CoUninitialize()
        return False


def local_identifiers(env=None) -> list[tuple[str, str]]:
    """Identificadores fuertes y MAC de ESTE equipo (para confirmar que una captura es de él)."""
    from .inventory import identifiers_from_scan

    def leer(e):
        inv = {}
        for clave in ("identity", "motherboard", "network"):
            fn = _funciones(e)[clave]
            try:
                r = fn(e)
            except Exception:  # cada colector es independiente: el resto del inventario se conserva
                log.debug("Inventario: falló %s", clave, exc_info=True)
                continue
            if r["status"] == OK:
                inv[clave] = r["data"]
        return identifiers_from_scan({"inventory": inv})

    if env is not None:
        return leer(env)
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        return leer(_crear_entorno())
    finally:
        gc.collect()
        if pythoncom:
            pythoncom.CoUninitialize()


def run_scan(progress=None, env=None, privilegiados: dict | None = None) -> dict:
    """Escanea el equipo. `progress(i, nombre, detalle, estado)` se llama por categoría.
    `privilegiados` (solo Linux): lo que leyó el ayudante con permisos (permisos_linux.datos_protegidos)."""
    if env is not None:
        return _escanear(progress, env)
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        entorno = _crear_entorno()
        if privilegiados and isinstance(entorno, _linux.EntornoLinux):
            entorno.usar_privilegiados(privilegiados)
        return _escanear(progress, entorno)
    finally:
        gc.collect()  # libera los objetos WMI antes de cerrar COM
        if pythoncom:
            pythoncom.CoUninitialize()
