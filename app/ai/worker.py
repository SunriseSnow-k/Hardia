from PySide6.QtCore import QThread, Signal

from .ollama_client import ChatStream, OllamaError


class AiWorker(QThread):
    chunk = Signal(int, str)       # (run_id, texto)
    completed = Signal(int)
    failed = Signal(int, str)

    def __init__(self, run_id: int, model: str, messages: list[dict]):
        super().__init__()
        self.run_id = run_id
        self._stream = ChatStream(model, messages)

    def cancel(self):
        self._stream.cancel()

    def run(self):
        try:
            for texto in self._stream.chunks():
                self.chunk.emit(self.run_id, texto)
            if not self._stream.cancelled:
                self.completed.emit(self.run_id)
        except OllamaError as e:
            if not self._stream.cancelled:
                self.failed.emit(self.run_id, str(e))
        except Exception as e:  # imprevisto: no debe cerrar el programa
            self.failed.emit(self.run_id, f"Error inesperado: {e}")