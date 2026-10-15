import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import app.ai.config as ia_config
from app.ai import ollama_client as oc, prompts
from app.db.database import Database
from app.db.repo import Repository
from app.diagnosis.engine import diagnose, load_rules


class Falso(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _json(self, codigo, datos):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _linea(self, texto, fin=False):
        d = {"message": {"role": "assistant", "content": texto}, "done": fin}
        self.wfile.write(json.dumps(d).encode() + b"\n")
        self.wfile.flush()

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": "llama3.2:3b"}, {"name": "qwen2.5:3b"}]})
        else:
            self._json(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        modelo = json.loads(self.rfile.read(n))["model"]
        if modelo == "no-existe":
            return self._json(404, {"error": "model 'no-existe' not found"})
        self.send_response(200)
        self.end_headers()
        try:
            if modelo == "lento":
                self._linea("A")
                time.sleep(3)
                self._linea("B")
            else:
                self._linea("Ho")
                self._linea("la")
            self._linea("", fin=True)
        except OSError:
            pass


@pytest.fixture
def servidor(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Falso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(oc, "PORT", srv.server_address[1])
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db)
    db.close()


def test_listar_modelos_y_has_model(servidor):
    modelos = oc.list_models()
    assert modelos == ["llama3.2:3b", "qwen2.5:3b"]
    assert oc.has_model(modelos, "llama3.2:3b")
    assert not oc.has_model(modelos, "llama3.2:1b")
    assert oc.has_model(["phi3:latest"], "phi3")
    assert not oc.has_model(modelos, "")


def test_stream_completo(servidor):
    assert "".join(oc.ChatStream("llama3.2:3b", []).chunks()) == "Hola"


def test_modelo_inexistente(servidor):
    with pytest.raises(oc.OllamaError, match="ollama pull"):
        list(oc.ChatStream("no-existe", []).chunks())


def test_cancelar_es_rapido(servidor):
    flujo = oc.ChatStream("lento", [])
    inicio, partes = time.time(), []
    for t in flujo.chunks():
        partes.append(t)
        flujo.cancel()
    assert partes == ["A"]
    assert time.time() - inicio < 2.5


def test_prompt_analisis():
    caso = {"equipo": "Laptop HP", "problem": "Se calienta"}
    scan = {"metrics": {"cpu_temp": 87}, "summary": {"cpu": "i5"}}
    res = diagnose("Se calienta, ventilador ruidoso", scan)
    msgs = prompts.analysis_messages(caso, scan, res)
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    texto = msgs[1]["content"]
    assert "Laptop HP" in texto and "87" in texto and res["causes"][0]["cause"] in texto


def test_relevant_rules():
    reglas = load_rules()
    top = prompts.relevant_rules("¿Qué hago si se calienta mucho y el ventilador suena fuerte?", reglas)
    assert top and top[0]["category"] == "Temperatura"
    assert prompts.relevant_rules("xyz qwerty", reglas) == []


def test_prompt_historial_y_cliente():
    hist = [
        {"code": "C-001", "fecha": "2026-09-25", "problema": "Arranque lento",
         "estado": "Entregado", "prioridad": "Media", "causa": "Demasiados programas al iniciar el sistema"},
        {"code": "C-002", "fecha": "2026-10-06", "problema": "Se calienta",
         "estado": "Recibido", "prioridad": "Alta", "causa": None},
    ]
    m = prompts.history_messages({"equipo": "Laptop HP", "serial": "SN-1"}, hist)
    assert "C-001" in m[1]["content"] and "sin diagnóstico" in m[1]["content"]
    res = diagnose("Se calienta, ventilador ruidoso", {"metrics": {"cpu_temp": 87}, "summary": {}})
    c = prompts.client_messages({"equipo": "Laptop HP", "cliente": "Luis Paredes",
                                 "problem": "Se calienta"}, res)
    assert "Luis Paredes" in c[1]["content"]


def test_config_guardar_y_cargar(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    # Por defecto: paquete de IA integrado con el modelo recomendado
    assert ia_config.load(repo) == {"enabled": True, "engine": "paquete", "model": "qwen3-4b",
                                    "mode": "rapido"}
    ia_config.save(repo, False, "qwen2.5:3b", "completo", engine="ollama")
    assert ia_config.load(repo) == {"enabled": False, "engine": "ollama", "model": "qwen2.5:3b",
                                    "mode": "completo"}
    ia_config.save(repo, True, "", "raro")
    assert ia_config.load(repo)["model"] == "llama3.2:3b" and ia_config.load(repo)["mode"] == "rapido"
    # Cada motor recuerda su modelo; un nombre que no es del paquete se corrige
    ia_config.save(repo, True, "qwen2.5-1.5b", "rapido", engine="paquete")
    assert ia_config.load(repo)["model"] == "qwen2.5-1.5b"
    ia_config.save(repo, True, "no-existe", "rapido", engine="paquete")
    assert ia_config.load(repo)["model"] == "qwen3-4b"
    ia_config.save(repo, True, "llama3.2:1b", "rapido", engine="ollama")
    ia_config.save(repo, True, "qwen2.5-1.5b", "rapido", engine="paquete")
    assert repo.get_setting("ia_model") == "llama3.2:1b"


def test_config_instalacion_anterior_sigue_con_ollama(repo):
    repo.set_setting("ia_model", "llama3.2:1b")  # guardado antes de existir el paquete
    cfg = ia_config.load(repo)
    assert cfg["engine"] == "ollama" and cfg["model"] == "llama3.2:1b"


def test_check_ai(repo, monkeypatch):
    def sin_ollama():
        raise oc.OllamaError("x")

    repo.set_setting("ia_engine", "ollama")

    monkeypatch.setattr(ia_config, "list_models", sin_ollama)
    ok, _, msg = ia_config.check_ai(repo)
    assert not ok and "Ollama" in msg

    monkeypatch.setattr(ia_config, "list_models", lambda: [])
    ok, _, msg = ia_config.check_ai(repo)
    assert not ok and "ollama pull" in msg

    monkeypatch.setattr(ia_config, "list_models", lambda: ["llama3.2:3b"])
    assert ia_config.check_ai(repo)[0] is True

    ia_config.save(repo, False, "llama3.2:3b", "rapido")
    ok, _, msg = ia_config.check_ai(repo)
    assert not ok and "desactivada" in msg


def test_historial_de_equipo_y_ajustes(repo):
    assert repo.get_setting("a", "x") == "x"
    repo.set_setting("a", "1")
    repo.set_setting("a", "2")
    assert repo.get_setting("a") == "2"

    c1 = repo.register_intake("Luis", "9", "SN-1", "Laptop", "Arranque lento")
    c2 = repo.register_intake("Luis", "9", "SN-1", "Laptop", "Se calienta")
    repo.save_diagnosis(c1, {"causes": [{"cause": "X", "priority": "Alta"}]})
    h = repo.equipment_history("sn-1")
    assert [x["code"] for x in h] == [c1, c2]
    assert h[0]["causa"] == "X" and h[1]["causa"] is None