from PySide6.QtCore import QThread, Signal

from . import paquete
from .llama_client import PaqueteStream
from .ollama_client import AiError, ChatStream


def crear_stream(model: str, messages: list[dict]) -> ChatStream:
    """Los modelos del paquete de IA van al motor integrado; cualquier otro nombre, a Ollama."""
    return (PaqueteStream if model in paquete.MODELOS else ChatStream)(model, messages)


class AiWorker(QThread):
    chunk = Signal(int, str)       # (run_id, texto)
    completed = Signal(int)
    failed = Signal(int, str)

    def __init__(self, run_id: int, model: str, messages: list[dict]):
        super().__init__()
        self.run_id = run_id
        self._stream = crear_stream(model, messages)

    def cancel(self):
        self._stream.cancel()

    def run(self):
        try:
            for texto in self._stream.chunks():
                self.chunk.emit(self.run_id, texto)
            if not self._stream.cancelled:
                self.completed.emit(self.run_id)
        except AiError as e:
            if not self._stream.cancelled:
                self.failed.emit(self.run_id, str(e))
        except Exception as e:  # imprevisto: no debe cerrar el programa
            self.failed.emit(self.run_id, f"Error inesperado: {e}")
