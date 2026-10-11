"""Configuración de la IA local (guardada en la tabla settings)."""
from .ollama_client import list_models, has_model, OllamaError

DEFAULT_MODEL = "llama3.2:3b"
MODELOS_SUGERIDOS = ["llama3.2:1b", "llama3.2:3b", "qwen2.5:3b"]


def load(repo) -> dict:
    return {
        "enabled": repo.get_setting("ia_enabled", "1") == "1",
        "model": repo.get_setting("ia_model", DEFAULT_MODEL) or DEFAULT_MODEL,
        "mode": repo.get_setting("ia_mode", "rapido"),  # "rapido" | "completo"
    }


def save(repo, enabled: bool, model: str, mode: str) -> None:
    repo.set_setting("ia_enabled", "1" if enabled else "0")
    repo.set_setting("ia_model", model.strip() or DEFAULT_MODEL)
    repo.set_setting("ia_mode", mode if mode in ("rapido", "completo") else "rapido")


def check_ai(repo) -> tuple[bool, str, str]:
    """(disponible, modelo, mensaje). Nunca lanza excepciones."""
    cfg = load(repo)
    modelo = cfg["model"]
    if not cfg["enabled"]:
        return False, modelo, ("La IA local está desactivada. Puede activarla en la "
                               "sección IA local.")
    try:
        instalados = list_models()
    except OllamaError:
        return False, modelo, ("No se detectó Ollama en este equipo. Inicie Ollama o "
                               "continúe con el resultado por reglas.")
    if not has_model(instalados, modelo):
        return False, modelo, (f"El modelo {modelo} no está instalado. En una terminal "
                               f"ejecute: ollama pull {modelo}")
    return True, modelo, "IA local lista."