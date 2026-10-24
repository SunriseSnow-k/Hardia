"""Permisos de administrador en Linux sin abrir la interfaz como root.

Equivale al botón «Reiniciar como administrador» de Windows: abre ayudante_root.py con pkexec (el
escritorio muestra su diálogo de contraseña) y le pide los datos protegidos del escaneo o la lectura
de los discos para la prueba de rendimiento. Una sesión abierta pide la contraseña una sola vez.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app import plataforma

log = logging.getLogger(__name__)

ARG_AYUDANTE = "--ayudante-root"  # main.py lo atiende en el programa empaquetado
# pkexec: 126 = el usuario canceló o no está autorizado; 127 = falló la autenticación o no hay agente
_MOTIVOS = {126: "se canceló el pedido de contraseña", 127: "no se pudo verificar la contraseña"}


class MMAE_PermisoDenegado(Exception):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """No se obtuvieron los permisos (se canceló, la contraseña no fue válida o no hay pkexec)."""


def disponible() -> bool:
    """Se pueden pedir permisos desde la interfaz: Linux, sin ser root y con pkexec (polkit)."""
    return plataforma.ES_LINUX and not plataforma.es_administrador() and shutil.which("pkexec") is not None


def orden_ayudante() -> list[str]:
    """Programa que pkexec ejecuta como root (rutas absolutas: pkexec no conserva la carpeta actual)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, ARG_AYUDANTE]
    return [sys.executable, "-I", str(Path(__file__).resolve().with_name("ayudante_root.py"))]


class MMAE_SesionAdmin:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Ayudante abierto con permisos. Usar con `with MMAE_SesionAdmin.abrir() as s:`."""

    def __init__(self, proc: subprocess.Popen):
        self._proc: subprocess.Popen | None = proc

    @classmethod
    def abrir(cls, orden: list[str] | None = None) -> "MMAE_SesionAdmin":
        pkexec = shutil.which("pkexec")
        if orden is None:
            if pkexec is None:
                raise MMAE_PermisoDenegado("este equipo no tiene pkexec (polkit) para pedir la contraseña")
            orden = [pkexec, *orden_ayudante()]
        try:
            proc = subprocess.Popen(orden, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # noqa: S603 (programa propio)
                                    stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd="/")
        except OSError as e:
            raise MMAE_PermisoDenegado(f"no se pudo pedir la contraseña ({e.strerror or e})") from e
        sesion = cls(proc)
        try:
            listo = sesion._recibir()  # espera a que el técnico escriba la contraseña
        except MMAE_PermisoDenegado:
            codigo = proc.wait()
            raise MMAE_PermisoDenegado(_MOTIVOS.get(codigo, f"el ayudante terminó con el código {codigo}")) from None
        if listo.get("tipo") != "listo":
            sesion.cerrar()
            raise MMAE_PermisoDenegado("respuesta inesperada del ayudante")
        log.info("Sesión con permisos de administrador abierta")
        return sesion

    def _enviar(self, orden: dict) -> None:
        try:
            if self._proc is None or self._proc.stdin is None:
                raise ValueError("sesión cerrada")
            self._proc.stdin.write(json.dumps(orden) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as e:
            raise MMAE_PermisoDenegado("el ayudante con permisos se cerró") from e

    def _recibir(self) -> dict:
        if self._proc is None or self._proc.stdout is None:
            raise MMAE_PermisoDenegado("la sesión con permisos ya se cerró")
        for linea in iter(self._proc.stdout.readline, ""):
            try:
                mensaje = json.loads(linea)
            except ValueError:
                continue  # texto ajeno (p. ej., avisos de bibliotecas al iniciar)
            if isinstance(mensaje, dict):
                return mensaje
        raise MMAE_PermisoDenegado("el ayudante con permisos se cerró")

    def datos(self) -> dict:
        """{"archivos": {ruta: texto}, "comandos": [[args, salida]]} para EntornoLinux.usar_privilegiados."""
        self._enviar({"orden": "datos"})
        return self._recibir()

    def leer_disco(self, ruta: str, duracion: float, cancelado=lambda: False, al_avanzar=None) -> dict:
        """Lectura del disco hecha por el ayudante, con el mismo resultado que ayudante_root.leer_dispositivo."""
        try:
            self._enviar({"orden": "leer_disco", "ruta": ruta, "duracion": duracion})
            cancelar_enviado = False
            while True:
                m = self._recibir()
                if m.get("tipo") == "resultado":
                    return {k: v for k, v in m.items() if k != "tipo"}
                if m.get("tipo") == "avance" and al_avanzar:
                    al_avanzar(m.get("t", 0.0), m.get("bytes", 0))
                if not cancelar_enviado and cancelado():
                    self._enviar({"orden": "cancelar"})
                    cancelar_enviado = True
        except MMAE_PermisoDenegado as e:
            return {"lectura_mb_s": None, "bytes": 0, "duracion_s": 0.0, "estado": "fallo", "motivo": str(e)}

    def cerrar(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()  # el ayudante termina al cerrarse su entrada
            proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            log.warning("El ayudante con permisos no terminó a tiempo")
        if proc.stdout:
            proc.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.cerrar()


def datos_protegidos() -> tuple[dict | None, str | None]:
    """(datos, None) o (None, motivo) — para un escaneo con permisos de una sola vez."""
    try:
        with MMAE_SesionAdmin.abrir() as s:
            return s.datos(), None
    except MMAE_PermisoDenegado as e:
        return None, str(e)


def sesion_si_hace_falta(rutas: list[str]) -> tuple["MMAE_SesionAdmin | None", str | None]:
    """Sesión para leer discos que este usuario no puede abrir (ninguna si no hace falta)."""
    if not disponible() or all(os.access(r, os.R_OK) for r in rutas if r):
        return None, None
    try:
        return MMAE_SesionAdmin.abrir(), None
    except MMAE_PermisoDenegado as e:
        return None, str(e)
