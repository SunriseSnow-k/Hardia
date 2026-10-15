"""Configuración de la IA local (guardada en la tabla settings).

Hay dos motores: el paquete de IA integrado (por defecto; se descarga desde la sección IA local)
y Ollama (avanzado, instalado aparte). Cada uno recuerda su propio modelo."""
from . import paquete
from .ollama_client import list_models, has_model, OllamaError

MOTORES = ("paquete", "ollama")
DEFAULT_MODEL = "llama3.2:3b"  # modelo por defecto de Ollama
MODELOS_SUGERIDOS = ["llama3.2:1b", "llama3.2:3b", "qwen2.5:3b"]


def _motor(repo) -> str:
    motor = repo.get_setting("ia_engine", "")
    if motor in MOTORES:
        return motor
    # Instalaciones anteriores al paquete: si ya habían elegido un modelo de Ollama, lo conservan
    return "ollama" if repo.get_setting("ia_model", "") else "paquete"


def modelo_paquete_por_defecto() -> str:
    instalados = paquete.modelos_instalados()
    return instalados[0] if instalados else paquete.RECOMENDADO


def load(repo) -> dict:
    motor = _motor(repo)
    if motor == "paquete":
        modelo = repo.get_setting("ia_paquete_model", "")
        if modelo not in paquete.MODELOS:
            modelo = modelo_paquete_por_defecto()
    else:
        modelo = repo.get_setting("ia_model", DEFAULT_MODEL) or DEFAULT_MODEL
    return {
        "enabled": repo.get_setting("ia_enabled", "1") == "1",
        "engine": motor,
        "model": modelo,
        "mode": repo.get_setting("ia_mode", "rapido"),  # "rapido" | "completo"
    }


def save(repo, enabled: bool, model: str, mode: str, engine: str | None = None) -> None:
    motor = engine if engine in MOTORES else _motor(repo)
    repo.set_setting("ia_enabled", "1" if enabled else "0")
    repo.set_setting("ia_engine", motor)
    if motor == "paquete":
        repo.set_setting("ia_paquete_model",
                         model if model in paquete.MODELOS else modelo_paquete_por_defecto())
    else:
        repo.set_setting("ia_model", model.strip() or DEFAULT_MODEL)
    repo.set_setting("ia_mode", mode if mode in ("rapido", "completo") else "rapido")


def check_ai(repo) -> tuple[bool, str, str]:
    """(disponible, modelo, mensaje). Nunca lanza excepciones."""
    cfg = load(repo)
    modelo = cfg["model"]
    if not cfg["enabled"]:
        return False, modelo, ("La IA local está desactivada. Puede activarla en la "
                               "sección IA local.")
    if cfg["engine"] == "paquete":
        try:
            if not paquete.motor_instalado() or not paquete.modelos_instalados():
                return False, modelo, ("El paquete de IA no está instalado. Puede descargarlo "
                                       "en la sección IA local.")
            if not paquete.modelo_instalado(modelo):
                return False, modelo, (f"El modelo {paquete.MODELOS[modelo]['nombre']} no está "
                                       "descargado. Puede descargarlo en la sección IA local.")
        except OSError:
            return False, modelo, "No se pudo revisar el paquete de IA."
        return True, modelo, "IA local lista."
    try:
        instalados = list_models()
    except OllamaError:
        return False, modelo, ("No se detectó Ollama en este equipo. Inicie Ollama o "
                               "continúe con el resultado por reglas.")
    if not has_model(instalados, modelo):
        return False, modelo, (f"El modelo {modelo} no está instalado. En una terminal "
                               f"ejecute: ollama pull {modelo}")
    return True, modelo, "IA local lista."


def nombre_modelo(modelo: str) -> str:
    """Nombre para mostrar (los modelos del paquete tienen nombre propio)."""
    return paquete.MODELOS[modelo]["nombre"] if modelo in paquete.MODELOS else modelo
