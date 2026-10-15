"""Paquete opcional de IA: descarga verificada, instalación del motor, cliente y página IA local."""
import hashlib
import io
import json
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtWidgets import QApplication

import app.ai.config as ia_config
from app.ai import paquete
from app.ai.llama_client import PaqueteStream
from app.ai.ollama_client import AiError, ChatStream, OllamaError
from app.ai.worker import crear_stream
from app.db.database import Database
from app.db.repo import Repository


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    def sin_ollama(*args, **kwargs):
        raise OllamaError("sin ollama")

    monkeypatch.setattr("app.ai.config.list_models", sin_ollama)
    monkeypatch.setattr("app.ui.pages.ia_local.list_models", sin_ollama)
    yield
    paquete.servidor.detener()


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db)
    db.close()


# ---------- Servidor de archivos falso (con Range) ----------
class Archivos(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    archivos: dict[str, bytes] = {}
    rangos: list[str] = []
    lento = False

    def log_message(self, *a):
        pass

    def do_GET(self):
        datos = self.archivos.get(self.path)
        if datos is None:
            self.send_response(404)
            self.end_headers()
            return
        inicio = 0
        rango = self.headers.get("Range")
        if rango:
            self.rangos.append(rango)
            inicio = int(rango.split("=")[1].rstrip("-"))
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(datos) - inicio))
        self.end_headers()
        try:
            for i in range(inicio, len(datos), 64 * 1024):
                self.wfile.write(datos[i:i + 64 * 1024])
                if self.lento:
                    time.sleep(0.05)
        except OSError:
            pass


@pytest.fixture
def web():
    Archivos.archivos, Archivos.rangos, Archivos.lento = {}, [], False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Archivos)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_descarga_completa_y_verificada(web, tmp_path):
    datos = bytes(range(256)) * 4000
    Archivos.archivos["/a.bin"] = datos
    destino = tmp_path / "a.bin"
    avances = []
    paquete.descargar(f"{web}/a.bin", destino, _sha(datos), len(datos), lambda h, t: avances.append(h))
    assert destino.read_bytes() == datos
    assert not destino.with_name("a.bin.part").exists()
    assert avances[-1] == len(datos)


def test_descarga_danada_se_descarta(web, tmp_path):
    datos = b"x" * 10000
    Archivos.archivos["/a.bin"] = datos
    destino = tmp_path / "a.bin"
    with pytest.raises(paquete.PaqueteError, match="dañado"):
        paquete.descargar(f"{web}/a.bin", destino, _sha(b"otra cosa"), len(datos))
    assert not destino.exists() and not destino.with_name("a.bin.part").exists()


def test_descarga_se_reanuda(web, tmp_path):
    datos = bytes(range(256)) * 1000
    Archivos.archivos["/a.bin"] = datos
    destino = tmp_path / "a.bin"
    destino.with_name("a.bin.part").write_bytes(datos[:100_000])
    paquete.descargar(f"{web}/a.bin", destino, _sha(datos), len(datos))
    assert Archivos.rangos == ["bytes=100000-"]
    assert destino.read_bytes() == datos


def test_descarga_cancelada_conserva_lo_bajado(web, tmp_path):
    datos = b"y" * 2_000_000
    Archivos.archivos["/a.bin"] = datos
    Archivos.lento = True
    destino = tmp_path / "a.bin"
    vistos = []
    with pytest.raises(paquete.Cancelado):
        paquete.descargar(f"{web}/a.bin", destino, _sha(datos), len(datos),
                          lambda h, t: vistos.append(h), cancelado=lambda: len(vistos) >= 2)
    parcial = destino.with_name("a.bin.part")
    assert parcial.exists() and 0 < parcial.stat().st_size < len(datos)
    assert not destino.exists()


def test_descarga_sin_conexion_da_mensaje_claro(tmp_path):
    with pytest.raises(paquete.PaqueteError, match="conexión a Internet"):
        paquete.descargar("http://127.0.0.1:9/nada", tmp_path / "a.bin", "0" * 64, 10)


def _zip_motor() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("llama-server.exe", b"MZ servidor")
        z.writestr("ggml.dll", b"dll")
        z.writestr("LICENSE-LLVM-OpenMP", b"licencia")
        z.writestr("llama-bench.exe", b"no hace falta")
        z.writestr("sub/otra.dll", b"anidada")
    return buf.getvalue()


def _catalogo_falso(monkeypatch, web):
    zip_motor = _zip_motor()
    modelo = b"GGUF" + b"\0" * 5000
    Archivos.archivos["/motor.zip"] = zip_motor
    Archivos.archivos["/modelo.gguf"] = modelo
    monkeypatch.setattr(paquete, "MOTOR", {**paquete.MOTOR, "url": f"{web}/motor.zip",
                                           "sha256": _sha(zip_motor), "tamano": len(zip_motor)})
    modelos = {k: dict(v) for k, v in paquete.MODELOS.items()}
    modelos["qwen2.5-1.5b"].update(url=f"{web}/modelo.gguf", sha256=_sha(modelo), tamano=len(modelo))
    monkeypatch.setattr(paquete, "MODELOS", modelos)


def test_instalar_motor_y_modelo(web, monkeypatch):
    _catalogo_falso(monkeypatch, web)
    assert not paquete.motor_instalado() and paquete.modelos_instalados() == []
    paquete.instalar_motor()
    motor = paquete.carpeta_motor()
    assert paquete.motor_instalado()
    nombres = {p.name for p in motor.iterdir()}
    assert {"llama-server.exe", "ggml.dll", "LICENSE-LLVM-OpenMP", "version.txt"} <= nombres
    assert "llama-bench.exe" not in nombres and "otra.dll" not in nombres
    assert {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"} <= nombres  # runtime de VC++
    assert not list(paquete.carpeta().glob("*.zip"))  # el zip se borra al terminar

    paquete.instalar_modelo("qwen2.5-1.5b")
    assert paquete.modelos_instalados() == ["qwen2.5-1.5b"] and paquete.instalado("qwen2.5-1.5b")
    paquete.eliminar_modelo("qwen2.5-1.5b")
    assert paquete.modelos_instalados() == []
    paquete.desinstalar()
    assert not paquete.motor_instalado()


def test_motor_de_otra_version_se_reinstala(web, monkeypatch):
    _catalogo_falso(monkeypatch, web)
    paquete.instalar_motor()
    (paquete.carpeta_motor() / "version.txt").write_text("b1", encoding="utf-8")
    assert not paquete.motor_instalado()


def test_servidor_sin_paquete_explica_que_falta():
    with pytest.raises(paquete.PaqueteError, match="no está instalado"):
        paquete.servidor.asegurar("qwen3-4b")


def test_check_ai_con_paquete(repo, monkeypatch):
    ok, modelo, msg = ia_config.check_ai(repo)
    assert not ok and modelo == "qwen3-4b" and "paquete de IA no está instalado" in msg
    monkeypatch.setattr(paquete, "motor_instalado", lambda: True)
    monkeypatch.setattr(paquete, "modelos_instalados", lambda: ["qwen2.5-1.5b"])
    monkeypatch.setattr(paquete, "modelo_instalado", lambda m: m == "qwen2.5-1.5b")
    ok, modelo, _ = ia_config.check_ai(repo)
    assert ok and modelo == "qwen2.5-1.5b"  # sin elección guardada, usa el modelo instalado
    ia_config.save(repo, True, "qwen3-4b", "rapido", engine="paquete")
    ok, _, msg = ia_config.check_ai(repo)
    assert not ok and "no está descargado" in msg


def test_crear_stream_elige_el_motor():
    assert isinstance(crear_stream("qwen3-4b", []), PaqueteStream)
    s = crear_stream("llama3.2:3b", [])
    assert isinstance(s, ChatStream) and not isinstance(s, PaqueteStream)


# ---------- Cliente del motor (eventos «data:») ----------
class Llama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    auth: list[str] = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(n))
        self.auth.append(self.headers.get("Authorization", ""))
        if cuerpo["messages"] and cuerpo["messages"][0]["content"] == "falla":
            datos = json.dumps({"error": {"message": "contexto excedido"}}).encode()
            self.send_response(400)
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for t in ("Ho", "la", None):
            if t is None:
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                d = {"choices": [{"delta": {"content": t}}]}
                self.wfile.write(b"data: " + json.dumps(d).encode() + b"\n\n")
            self.wfile.flush()


@pytest.fixture
def motor_falso(monkeypatch):
    Llama.auth = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Llama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(paquete.servidor, "asegurar", lambda m, c=None: True)
    monkeypatch.setattr(paquete.servidor, "puerto", srv.server_address[1])
    monkeypatch.setattr(paquete.servidor, "clave", "secreta")
    yield
    srv.shutdown()
    srv.server_close()


def test_paquete_stream(motor_falso):
    assert "".join(PaqueteStream("qwen3-4b", [{"role": "user", "content": "hola"}]).chunks()) == "Hola"
    assert Llama.auth == ["Bearer secreta"]


def test_paquete_stream_error(motor_falso):
    with pytest.raises(AiError, match="contexto excedido"):
        list(PaqueteStream("qwen3-4b", [{"role": "user", "content": "falla"}]).chunks())


def test_paquete_stream_cancelado_mientras_carga(monkeypatch):
    monkeypatch.setattr(paquete.servidor, "asegurar", lambda m, c=None: False)
    flujo = PaqueteStream("qwen3-4b", [])
    flujo.cancel()
    assert list(flujo.chunks()) == []


# ---------- Página IA local ----------
def test_pagina_descarga_e_instala(qapp, repo, web, monkeypatch):
    from app.ui.pages.ia_local import IaLocalPage
    _catalogo_falso(monkeypatch, web)
    pagina = IaLocalPage(repo)
    fila = next(f for f in pagina.filas if f.modelo_id == "qwen2.5-1.5b")
    assert fila.boton.text() == "Descargar" and "No instalado" in fila.estado.text()
    assert "no instalado" in pagina.estado.text()

    fila.boton.click()
    limite = time.time() + 15
    while pagina.descarga is not None and time.time() < limite:
        qapp.processEvents()
        time.sleep(0.02)
    assert pagina.descarga is None
    assert paquete.instalado("qwen2.5-1.5b")
    assert fila.boton.text() == "Eliminar"
    # Lo configurado no funcionaba: queda en uso el modelo recién instalado
    cfg = ia_config.load(repo)
    assert cfg["engine"] == "paquete" and cfg["model"] == "qwen2.5-1.5b"
    assert ia_config.check_ai(repo)[0]
    assert "listo" in pagina.estado.text()
    pagina.shutdown()


# ---------- Distribución: recursos, registro ----------
def test_recursos_incluidos():
    from app.paths import recurso
    ico = recurso("assets", "icono.ico").read_bytes()
    assert ico[:4] == b"\0\0\1\0" and int.from_bytes(ico[4:6], "little") >= 5  # varios tamaños
    assert recurso("assets", "icono.png").exists()
    licencias = recurso("assets", "LICENCIAS_TERCEROS.txt").read_text(encoding="utf-8")
    assert "llama.cpp" in licencias and "LibreHardwareMonitor" in licencias


def test_registro_guarda_errores_no_controlados(monkeypatch):
    import logging
    import sys

    from app import registro
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    avisos = []
    monkeypatch.setattr(registro, "_avisar", lambda detalle, resumen: avisos.append(resumen))
    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    try:
        ruta = registro.configurar()
        try:
            raise ValueError("falla de prueba")
        except ValueError:
            registro._excepthook(*sys.exc_info())
        for h in raiz.handlers:
            h.flush()
        texto = ruta.read_text(encoding="utf-8")
        assert "Inicio de" in texto and "falla de prueba" in texto
        assert avisos == ["ValueError: falla de prueba"]  # y se avisa al usuario
    finally:
        for h in raiz.handlers[:]:
            if h not in antes:
                raiz.removeHandler(h)
                h.close()
