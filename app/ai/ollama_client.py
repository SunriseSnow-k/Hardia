"""Cliente mínimo de Ollama. Solo habla con 127.0.0.1 (nada sale a Internet)."""
import contextlib
import http.client
import json
import queue
import socket
import threading

HOST = "127.0.0.1"
PORT = 11434
KEEP_ALIVE = "10m"  # mantiene el modelo cargado entre consultas
TIMEOUT_RESPUESTA = 300  # segundos máximos de espera sin datos de Ollama


class AiError(Exception):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Error al hablar con el motor de IA (el mensaje se muestra al usuario)."""


OllamaError = AiError  # nombre anterior, lo siguen usando las pruebas y la página de IA


def list_models(timeout: float = 1.5) -> list[str]:
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        if resp.status != 200:
            raise OllamaError(f"Ollama respondió con el código {resp.status}.")
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", []) if m.get("name")]
    except OllamaError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as e:
        raise OllamaError("No se pudo conectar con Ollama.") from e
    finally:
        conn.close()


def has_model(models: list[str], wanted: str) -> bool:
    wanted = wanted.strip().lower()
    if not wanted:
        return False
    nombres = [m.lower() for m in models]
    if wanted in nombres:
        return True
    return ":" not in wanted and f"{wanted}:latest" in nombres


def _mensaje_error(texto: str, status: int, model: str) -> str:
    bajo = texto.lower()
    if status == 404 or "not found" in bajo:
        return f"El modelo {model} no está instalado. En una terminal ejecute: ollama pull {model}"
    if "memory" in bajo:
        return ("Memoria insuficiente para este modelo. Pruebe uno más ligero, "
                "por ejemplo llama3.2:1b.")
    return texto or f"Ollama respondió con el código {status}."


class ChatStream:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Respuesta de chat por streaming, cancelable desde cualquier hilo.

    La lectura de red ocurre en un hilo auxiliar. `chunks()` espera los datos
    en una cola y revisa cada 0,2 s si se canceló, así la cancelación responde
    al instante aunque Ollama no esté enviando nada (por ejemplo, cargando el
    modelo). En Windows, cerrar el socket no interrumpe una lectura bloqueada.
    """

    def __init__(self, model: str, messages: list[dict], num_predict: int = 350):
        self.model = model
        self.messages = messages
        self.num_predict = num_predict
        self.cancelled = False
        self._sock = None
        self._q: queue.Queue = queue.Queue()

    def cancel(self):
        """Marca la cancelación y corta la conexión (Ollama deja de generar)."""
        self.cancelled = True
        sock = self._sock
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def chunks(self):
        threading.Thread(target=self._leer, daemon=True).start()
        while True:
            if self.cancelled:
                return
            try:
                tipo, valor = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if tipo == "chunk":
                yield valor
            elif tipo == "error":
                if not self.cancelled:
                    raise valor
                return
            else:  # "end"
                return

    # ---------- hilo lector ----------
    def _conexion(self):
        """Conexión con el motor; None si se canceló antes de tenerla."""
        return http.client.HTTPConnection(HOST, PORT, timeout=TIMEOUT_RESPUESTA)

    def _leer(self):
        conn = None
        try:
            conn = self._conexion()
            if conn is not None:
                self._leer_respuesta(conn)
        except AiError as e:
            self._q.put(("error", e))
        except Exception as e:  # imprevisto: se informa, no se cierra el programa
            self._q.put(("error", AiError(f"Error inesperado: {e}")))
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: S110 (cerrar una conexión ya rota no debe ocultar el error real)
                pass
            self._q.put(("end", None))

    def _leer_respuesta(self, conn):
        cuerpo = json.dumps({
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0.2, "num_predict": self.num_predict, "num_ctx": 4096},
        }).encode("utf-8")
        try:
            conn.request("POST", "/api/chat", body=cuerpo,
                         headers={"Content-Type": "application/json"})
            self._sock = conn.sock
            if self.cancelled:
                return
            resp = conn.getresponse()
        except TimeoutError as e:
            raise OllamaError("Ollama tardó demasiado en responder.") from e
        except (OSError, http.client.HTTPException) as e:
            if self.cancelled:
                return
            raise OllamaError("No se pudo conectar con Ollama. ¿Está en ejecución?") from e

        if resp.status != 200:
            try:
                texto = str(json.loads(resp.read() or b"{}").get("error", ""))
            except (ValueError, OSError, http.client.HTTPException):
                texto = ""
            raise OllamaError(_mensaje_error(texto, resp.status, self.model))

        while not self.cancelled:
            try:
                linea = resp.readline()
            except TimeoutError as e:
                raise OllamaError("Ollama tardó demasiado en responder.") from e
            except (OSError, http.client.HTTPException) as e:
                if self.cancelled:
                    return
                raise OllamaError("Se perdió la conexión con Ollama.") from e
            if not linea:
                return
            try:
                data = json.loads(linea)
            except ValueError:
                continue
            if "error" in data:
                raise OllamaError(_mensaje_error(str(data["error"]), 200, self.model))
            texto = (data.get("message") or {}).get("content", "")
            if texto:
                self._q.put(("chunk", texto))
            if data.get("done"):
                return
