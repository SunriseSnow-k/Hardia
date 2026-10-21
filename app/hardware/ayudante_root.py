"""Ayudante con permisos de administrador para Linux (lo lanza permisos_linux.py con pkexec).

En Linux la interfaz no se abre como root: cuando el técnico pide un escaneo o una prueba de discos
con permisos, el programa abre este ayudante una sola vez (el escritorio pide la contraseña) y le
hace pedidos por una tubería. El ayudante solo lee: archivos fijos de /sys, la salida de dmidecode y
smartctl, y la velocidad de lectura de discos (nunca devuelve su contenido ni escribe en ellos).

Usa solo la biblioteca estándar y no importa nada del programa: en desarrollo se ejecuta como
`python -I ayudante_root.py` y empaquetado como `SistemaDiagnostico --ayudante-root`.

Protocolo: una orden JSON por línea en la entrada y respuestas JSON por línea en la salida.
  al iniciar                                       -> {"tipo": "listo"}
  {"orden": "datos"}                               -> {"tipo": "datos", "archivos": {...}, "comandos": [...]}
  {"orden": "leer_disco", "ruta": "/dev/sda", "duracion": 30}
                                                   -> {"tipo": "avance", "t", "bytes"}… {"tipo": "resultado", …}
  {"orden": "cancelar"} durante una lectura la detiene; al cerrarse la entrada el ayudante termina.
"""
import json
import mmap
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import time

# Dispositivos de bloque que no son discos (memoria, imágenes, lectores ópticos, volúmenes lógicos)
NO_DISCO = ("loop", "ram", "zram", "sr", "fd", "dm-", "md", "nbd")
# Datos de /sys/class/dmi/id que solo root puede leer
ARCHIVOS_PROTEGIDOS = ("product_serial", "product_uuid", "board_serial", "chassis_serial")
BLOQUE = 1024 * 1024  # 1 MiB (múltiplo del tamaño de sector, requerido por O_DIRECT)


def ejecutar(*args: str) -> str | None:
    """Salida de un programa del sistema (None si no está o no da salida). Igual que
    EntornoLinux.ejecutar, para que el escaneo use la respuesta tal cual."""
    programa = shutil.which(args[0])
    if not programa:
        return None
    try:
        r = subprocess.run([programa, *args[1:]], capture_output=True, text=True,  # noqa: S603 (programas fijos, sin shell)
                           timeout=20, errors="replace", env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.stdout.strip() else None  # smartctl avisa con bits del código de salida


def discos(raiz: str = "") -> list[str]:
    """Nombres de los discos de /sys/block (sin memoria, imágenes ni lectores ópticos)."""
    try:
        nombres = sorted(os.listdir(f"{raiz}/sys/block"))
    except OSError:
        return []
    return [n for n in nombres if not n.startswith(NO_DISCO) and not re.search(r"boot\d+$|rpmb$", n)]


def datos(raiz: str = "") -> dict:
    """Lo que el escaneo no puede leer sin root."""
    archivos = {}
    for nombre in ARCHIVOS_PROTEGIDOS:
        ruta = f"/sys/class/dmi/id/{nombre}"
        try:
            with open(f"{raiz}{ruta}", encoding="utf-8", errors="replace") as f:
                archivos[ruta] = f.read().strip()
        except OSError:
            pass
    ordenes = [("dmidecode", "-t", "17")] + [("smartctl", "-j", "-a", f"/dev/{n}") for n in discos(raiz)]
    return {"tipo": "datos", "archivos": archivos, "comandos": [[list(o), ejecutar(*o)] for o in ordenes]}


def es_disco(ruta: str) -> bool:
    """Solo se leen discos completos de /dev que el kernel lista en /sys/block."""
    m = re.fullmatch(r"/dev/([A-Za-z0-9]+)", ruta or "")
    if not m or m.group(1) not in discos():
        return False
    try:
        return stat.S_ISBLK(os.stat(ruta).st_mode)
    except OSError:
        return False


def leer_dispositivo(ruta: str, duracion: float, cancelado=lambda: False, al_avanzar=None) -> dict:
    """Lectura secuencial sin caché (O_DIRECT) de un dispositivo de bloque, solo lectura.
    Devuelve {lectura_mb_s, bytes, duracion_s, estado, motivo[, cancelado]}."""
    base = {"lectura_mb_s": None, "bytes": 0, "duracion_s": 0.0, "estado": "ok", "motivo": ""}
    try:
        fd = os.open(ruta, os.O_RDONLY | getattr(os, "O_DIRECT", 0))
    except PermissionError:
        return {**base, "estado": "no_autorizado", "motivo": "requiere permisos de administrador"}
    except OSError as e:
        return {**base, "estado": "fallo", "motivo": f"Linux no permitió abrir la unidad ({e.strerror})"}
    buf = mmap.mmap(-1, BLOQUE)  # alineado a página, como exige O_DIRECT
    total, cancelada = 0, False
    t0 = ultimo_aviso = time.perf_counter()
    try:
        while True:
            try:
                leidos = os.readv(fd, [buf])
            except OSError:
                break  # error de lectura: se usa lo leído
            if leidos <= 0:
                break
            total += leidos
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
        buf.close()
        os.close(fd)
    dur = time.perf_counter() - t0
    if total == 0:
        return {**base, "estado": "fallo", "motivo": "no se pudo leer la unidad", "duracion_s": round(dur, 1)}
    return {**base, "lectura_mb_s": round(total / 1e6 / max(dur, 1e-6), 1), "bytes": total,
            "duracion_s": round(dur, 1), "cancelado": cancelada}


def _enviar(salida, mensaje: dict) -> None:
    salida.write(json.dumps(mensaje) + "\n")
    salida.flush()


def _hay_cancelacion(entrada) -> bool:
    """Revisa sin esperar si llegó una orden durante la lectura (cancelar o entrada cerrada)."""
    try:
        listo, _, _ = select.select([entrada], [], [], 0)
    except (OSError, ValueError):
        return True
    if not listo:
        return False
    linea = entrada.readline()
    return not linea or "cancelar" in linea


def atender(entrada=sys.stdin, salida=sys.stdout) -> int:
    _enviar(salida, {"tipo": "listo"})
    for linea in iter(entrada.readline, ""):
        try:
            orden = json.loads(linea)
        except ValueError:
            continue
        if not isinstance(orden, dict):
            continue
        if orden.get("orden") == "datos":
            _enviar(salida, datos())
        elif orden.get("orden") == "leer_disco":
            ruta = str(orden.get("ruta") or "")
            if not es_disco(ruta):
                _enviar(salida, {"tipo": "resultado", "lectura_mb_s": None, "bytes": 0, "duracion_s": 0.0,
                                 "estado": "fallo", "motivo": "no es un disco de este equipo"})
                continue
            try:
                duracion = min(max(float(orden.get("duracion", 30)), 0.5), 600.0)
            except (TypeError, ValueError):
                duracion = 30.0
            r = leer_dispositivo(ruta, duracion, lambda: _hay_cancelacion(entrada),
                                 lambda t, b: _enviar(salida, {"tipo": "avance", "t": t, "bytes": b}))
            _enviar(salida, {"tipo": "resultado", **r})
        elif orden.get("orden") == "fin":
            break
    return 0


if __name__ == "__main__":
    sys.exit(atender())
