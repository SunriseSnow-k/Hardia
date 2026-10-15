"""Chat con el motor del paquete de IA (llama-server, API compatible con OpenAI).

Reutiliza el hilo lector y la cancelación de ChatStream; solo cambia cómo se conecta y
cómo se lee la respuesta (eventos «data: …» en lugar de líneas JSON de Ollama)."""
import http.client
import json

from . import paquete
from .ollama_client import TIMEOUT_RESPUESTA, AiError, ChatStream


class PaqueteStream(ChatStream):
    def _conexion(self):
        if not paquete.servidor.asegurar(self.model, lambda: self.cancelled):
            return None
        return http.client.HTTPConnection("127.0.0.1", paquete.servidor.puerto, timeout=TIMEOUT_RESPUESTA)

    def _leer_respuesta(self, conn):
        cuerpo = json.dumps({
            "messages": self.messages,
            "stream": True,
            "temperature": 0.2,
            "max_tokens": self.num_predict,
        }).encode("utf-8")
        try:
            conn.request("POST", "/v1/chat/completions", body=cuerpo,
                         headers={"Content-Type": "application/json",
                                  "Authorization": f"Bearer {paquete.servidor.clave}"})
            self._sock = conn.sock
            if self.cancelled:
                return
            resp = conn.getresponse()
        except TimeoutError as e:
            raise AiError("El motor de IA tardó demasiado en responder.") from e
        except (OSError, http.client.HTTPException) as e:
            if self.cancelled:
                return
            raise AiError("No se pudo conectar con el motor de IA.") from e

        if resp.status != 200:
            try:
                error = json.loads(resp.read() or b"{}").get("error") or {}
                texto = error.get("message", "") if isinstance(error, dict) else str(error)
            except (ValueError, OSError, http.client.HTTPException):
                texto = ""
            raise AiError(texto or f"El motor de IA respondió con el código {resp.status}.")

        while not self.cancelled:
            try:
                linea = resp.readline()
            except TimeoutError as e:
                raise AiError("El motor de IA tardó demasiado en responder.") from e
            except (OSError, http.client.HTTPException) as e:
                if self.cancelled:
                    return
                raise AiError("Se perdió la conexión con el motor de IA.") from e
            if not linea:
                return
            linea = linea.strip()
            if not linea.startswith(b"data:"):
                continue
            dato = linea[5:].strip()
            if dato == b"[DONE]":
                return
            try:
                data = json.loads(dato)
            except ValueError:
                continue
            if "error" in data:
                error = data["error"]
                raise AiError(error.get("message", str(error)) if isinstance(error, dict) else str(error))
            for opcion in data.get("choices") or []:
                texto = (opcion.get("delta") or {}).get("content") or ""
                if texto:
                    self._q.put(("chunk", texto))
