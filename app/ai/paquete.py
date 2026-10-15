"""Paquete opcional de IA: motor llama.cpp + un modelo GGUF, descargados una sola vez.

Todo se guarda en %APPDATA%\\SistemaDiagnostico\\IA. La descarga es lo único que usa Internet;
después el motor funciona sin conexión y escucha solo en 127.0.0.1. Cada archivo tiene su
versión y su SHA-256 fijos: si lo descargado no coincide, se descarta.
"""
import hashlib
import http.client
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from app.paths import data_dir
from app.version import APP_NAME, VERSION

from .ollama_client import AiError

log = logging.getLogger(__name__)

MOTOR: dict[str, Any] = {
    "version": "b11620",
    "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11620/"
           "llama-b11620-bin-win-cpu-x64.zip",
    "sha256": "f77646c3cea8e775bb56ca0e391e8324112d29e5b783e1d92f2ceae8627deb3c",
    "tamano": 19_553_388,
    "licencia": "MIT",
}
# Del zip solo se conserva lo que necesita el servidor
_ARCHIVOS_MOTOR = ("llama-server.exe",)
# Runtime de Visual C++ que pide llama.cpp; PySide6 lo trae, así no hace falta instalarlo aparte
_RUNTIME_VC = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")

MODELOS: dict[str, dict[str, Any]] = {
    "qwen3-4b": {
        "nombre": "Recomendado · Qwen3 4B Instruct",
        "descripcion": "Mejores respuestas en español. Conviene un equipo con 8 GB de RAM o más.",
        "archivo": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/"
               "a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "sha256": "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
        "tamano": 2_497_281_120,
        "ram_gb": 8,
        "licencia": "Apache 2.0",
    },
    "qwen2.5-1.5b": {
        "nombre": "Ligero · Qwen2.5 1.5B Instruct",
        "descripcion": "Más rápido y liviano, para equipos modestos (4 GB de RAM). Respuestas más simples.",
        "archivo": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
               "91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        "tamano": 1_117_320_736,
        "ram_gb": 4,
        "licencia": "Apache 2.0",
    },
}
RECOMENDADO = "qwen3-4b"

CONTEXTO = 4096
ESPERA_CARGA = 300  # segundos máximos para que el motor cargue el modelo
_MARGEN_DISCO = 300 * 1024 * 1024


class PaqueteError(AiError):
    """Error de instalación o de ejecución del paquete (el mensaje se muestra al usuario)."""


class Cancelado(Exception):
    """El usuario canceló la descarga."""


# ---------- Rutas y estado ----------
def carpeta() -> Path:
    path = data_dir() / "IA"
    path.mkdir(parents=True, exist_ok=True)
    return path


def carpeta_motor() -> Path:
    return carpeta() / "motor"


def carpeta_modelos() -> Path:
    path = carpeta() / "modelos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ruta_modelo(modelo_id: str) -> Path:
    return carpeta_modelos() / MODELOS[modelo_id]["archivo"]


def motor_instalado() -> bool:
    m = carpeta_motor()
    try:
        version = (m / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return version == MOTOR["version"] and (m / "llama-server.exe").exists()


def modelo_instalado(modelo_id: str) -> bool:
    if modelo_id not in MODELOS:
        return False
    path = ruta_modelo(modelo_id)
    return path.exists() and path.stat().st_size == MODELOS[modelo_id]["tamano"]


def modelos_instalados() -> list[str]:
    return [m for m in MODELOS if modelo_instalado(m)]


def instalado(modelo_id: str) -> bool:
    return motor_instalado() and modelo_instalado(modelo_id)


def ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        return 0.0


def tamano_texto(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB".replace(".", ",") if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


# ---------- Descarga ----------
def _sha256(path: Path, cancelado) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while bloque := f.read(4 * 1024 * 1024):
            if cancelado():
                raise Cancelado
            h.update(bloque)
    return h.hexdigest()


def _validar_url(url: str) -> None:
    """Solo descargas https (o http hacia este mismo equipo, para las pruebas): nunca file: ni otros esquemas."""
    p = urllib.parse.urlsplit(url)
    if p.scheme == "https" or (p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")):
        return
    raise PaqueteError(f"Dirección de descarga no permitida: {url}")


def descargar(url: str, destino: Path, sha256: str, tamano: int, progreso=None, cancelado=lambda: False):
    """Descarga a <destino>.part (se reanuda si quedó a medias), verifica el SHA-256 y renombra.
    progreso(hecho, total) se llama desde este hilo."""
    progreso = progreso or (lambda hecho, total: None)
    parcial = destino.with_name(destino.name + ".part")
    hecho = parcial.stat().st_size if parcial.exists() else 0
    if hecho > tamano:
        parcial.unlink()
        hecho = 0
    libre = shutil.disk_usage(destino.parent).free
    if libre < tamano - hecho + _MARGEN_DISCO:
        raise PaqueteError(f"No hay espacio suficiente en el disco: se necesitan "
                           f"{tamano_texto(tamano - hecho + _MARGEN_DISCO)} libres.")

    if hecho < tamano:
        cabeceras = {"User-Agent": f"{APP_NAME.replace(' ', '')}/{VERSION}"}
        if hecho:
            cabeceras["Range"] = f"bytes={hecho}-"
        try:
            _validar_url(url)
            peticion = urllib.request.Request(url, headers=cabeceras)  # noqa: S310 (esquema validado arriba)
            with urllib.request.urlopen(peticion, timeout=30) as resp:  # noqa: S310
                if hecho and resp.status != 206:  # el servidor no reanuda: se empieza de cero
                    hecho = 0
                with open(parcial, "ab" if hecho else "wb") as f:
                    while True:
                        if cancelado():
                            raise Cancelado
                        bloque = resp.read1(256 * 1024)  # devuelve lo que haya llegado
                        if not bloque:
                            break
                        f.write(bloque)
                        hecho += len(bloque)
                        progreso(hecho, tamano)
        except urllib.error.HTTPError as e:
            raise PaqueteError(f"El servidor de descarga respondió con el código {e.code}. "
                               "Inténtelo más tarde.") from e
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise PaqueteError("Se interrumpió la descarga. Revise la conexión a Internet y pulse "
                               "de nuevo «Descargar»: continuará donde quedó.") from e

    if _sha256(parcial, cancelado) != sha256:
        parcial.unlink(missing_ok=True)
        raise PaqueteError("El archivo descargado está dañado o no es el esperado y se descartó. "
                           "Inténtelo de nuevo.")
    os.replace(parcial, destino)


def _runtime_vc() -> list[Path]:
    """DLL del runtime de VC++ que ya trae el programa (junto a PySide6 o en su carpeta)."""
    carpetas = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
    try:
        import PySide6
        carpetas.insert(0, Path(PySide6.__file__).parent)
    except Exception:  # noqa: S110 (sin PySide6 se buscan las DLL en las demás carpetas)
        pass
    encontradas = []
    for dll in _RUNTIME_VC:
        for c in carpetas:
            if str(c) not in ("", ".") and (c / dll).exists():
                encontradas.append(c / dll)
                break
    return encontradas


def instalar_motor(progreso=None, cancelado=lambda: False):
    if motor_instalado():
        return
    zip_path = carpeta() / Path(MOTOR["url"]).name
    descargar(MOTOR["url"], zip_path, MOTOR["sha256"], MOTOR["tamano"], progreso, cancelado)
    tmp = carpeta() / "motor.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        with zipfile.ZipFile(zip_path) as z:
            for nombre in z.namelist():
                base = Path(nombre).name
                if not base or "/" in nombre.rstrip("/") or "\\" in nombre:
                    continue  # solo archivos de la raíz del zip
                if base.lower().endswith(".dll") or base.startswith("LICENSE") or base in _ARCHIVOS_MOTOR:
                    (tmp / base).write_bytes(z.read(nombre))
    except (zipfile.BadZipFile, OSError) as e:
        raise PaqueteError(f"No se pudo descomprimir el motor de IA: {e}") from e
    for dll in _runtime_vc():
        shutil.copy2(dll, tmp / dll.name)
    (tmp / "version.txt").write_text(MOTOR["version"], encoding="utf-8")
    servidor.detener()
    shutil.rmtree(carpeta_motor(), ignore_errors=True)
    os.replace(tmp, carpeta_motor())
    zip_path.unlink(missing_ok=True)
    log.info("Motor de IA %s instalado", MOTOR["version"])


def instalar_modelo(modelo_id: str, progreso=None, cancelado=lambda: False):
    if modelo_instalado(modelo_id):
        return
    m = MODELOS[modelo_id]
    descargar(m["url"], ruta_modelo(modelo_id), m["sha256"], m["tamano"], progreso, cancelado)
    log.info("Modelo de IA %s instalado", modelo_id)


def eliminar_modelo(modelo_id: str):
    if servidor.modelo == modelo_id:
        servidor.detener()
    path = ruta_modelo(modelo_id)
    for p in (path, path.with_name(path.name + ".part")):
        p.unlink(missing_ok=True)


def desinstalar():
    """Elimina el motor y todos los modelos."""
    servidor.detener()
    shutil.rmtree(carpeta(), ignore_errors=True)
    if carpeta().exists() and any(carpeta().iterdir()):
        raise OSError("Algunos archivos están en uso; cierre el programa e inténtelo de nuevo.")


# ---------- Servidor local ----------
def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _estado_salud(puerto: int) -> int:
    """Código HTTP de /health (200 listo, 503 cargando) o 0 si no responde."""
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=1)
    try:
        conn.request("GET", "/health")
        return conn.getresponse().status
    except (OSError, http.client.HTTPException):
        return 0
    finally:
        conn.close()


def _hilos() -> int:
    try:
        import psutil
        return max(1, psutil.cpu_count(logical=False) or 1)
    except Exception:
        return max(1, (os.cpu_count() or 2) // 2)


class Servidor:
    """llama-server en segundo plano, con un modelo cargado. Se inicia al primer uso y se
    reinicia si se pide otro modelo. Si el programa se cierra de golpe, Windows lo termina
    (objeto de trabajo con KILL_ON_JOB_CLOSE)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._job = None
        self.modelo: str | None = None
        self.puerto = 0
        self.clave = ""

    def activo(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def asegurar(self, modelo_id: str, cancelado=lambda: False) -> bool:
        """Deja el servidor listo con ese modelo. False si se canceló mientras cargaba."""
        with self._lock:
            if not (self.activo() and self.modelo == modelo_id):
                self._detener()
                self._iniciar(modelo_id)
            proc, puerto = self._proc, self.puerto
        assert proc is not None  # _iniciar lanza PaqueteError si no puede arrancar
        limite = time.monotonic() + ESPERA_CARGA
        while time.monotonic() < limite:
            if cancelado():
                return False
            if proc.poll() is not None:
                raise PaqueteError("El motor de IA se cerró al cargar el modelo. Puede faltar memoria: "
                                   "pruebe el modelo Ligero. Detalle en " + str(carpeta() / "motor.log"))
            if _estado_salud(puerto) == 200:
                return True
            time.sleep(0.3)
        raise PaqueteError("El motor de IA tardó demasiado en cargar el modelo.")

    def _iniciar(self, modelo_id: str):
        if not motor_instalado():
            raise PaqueteError("El paquete de IA no está instalado. Instálelo en la sección IA local.")
        if not modelo_instalado(modelo_id):
            raise PaqueteError(f"El modelo {MODELOS.get(modelo_id, {}).get('nombre', modelo_id)} no está "
                               "descargado. Descárguelo en la sección IA local.")
        self.puerto = _puerto_libre()
        self.clave = secrets.token_hex(16)  # solo este programa puede usar el servidor
        exe = carpeta_motor() / "llama-server.exe"
        args = [str(exe), "-m", str(ruta_modelo(modelo_id)), "--host", "127.0.0.1",
                "--port", str(self.puerto), "-c", str(CONTEXTO), "-np", "1", "-t", str(_hilos()),
                "--no-webui", "--api-key", self.clave]
        salida = open(carpeta() / "motor.log", "wb")  # noqa: SIM115 (el proceso hijo hereda el archivo; se cierra abajo)
        try:
            self._proc = subprocess.Popen(  # noqa: S603 (ejecutable y argumentos propios, sin shell)
                args, cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=salida, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise PaqueteError(f"No se pudo iniciar el motor de IA: {e}") from e
        finally:
            salida.close()
        self.modelo = modelo_id
        self._job = _atar_al_programa(self._proc.pid)
        log.info("Motor de IA iniciado (modelo %s, puerto %s)", modelo_id, self.puerto)

    def _detener(self):
        proc, self._proc = self._proc, None
        self.modelo = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._job = None

    def detener(self):
        with self._lock:
            self._detener()


def _atar_al_programa(pid: int):
    """Asigna el proceso a un objeto de trabajo que Windows cierra junto con este programa."""
    if sys.platform != "win32":
        return None
    try:
        import win32api
        import win32con
        import win32job
        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        h = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        try:
            win32job.AssignProcessToJobObject(job, h)
        finally:
            win32api.CloseHandle(h)
        return job
    except Exception:
        log.warning("No se pudo atar el motor de IA al programa", exc_info=True)
        return None


servidor = Servidor()
