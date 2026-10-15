"""Construcción de los mensajes para el modelo. Solo se envían datos del caso."""
import re

from app.diagnosis.engine import normalizar

SISTEMA = (
    "Eres el asistente de un taller de mantenimiento de computadoras. "
    "Respondes siempre en español, con frases cortas y claras. "
    "Usas únicamente los datos que se te entregan y no inventas mediciones ni fallas. "
    "Hablas de posibles causas, nunca de certezas."
)
_STOP = {"como", "para", "cual", "esta", "este", "tiene", "hacer", "puedo", "porque",
         "cuando", "donde", "pero", "sobre", "cuales", "muy"}


def _g(caso, clave, defecto=""):
    try:
        valor = caso[clave]
    except (KeyError, IndexError):
        return defecto
    return defecto if valor is None else valor


def _msgs(usuario: str) -> list[dict]:
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


def _datos_scan(scan) -> str:
    if not scan:
        return "Sin escaneo del equipo."
    m = scan.get("metrics", {}) or {}
    r = scan.get("summary", {}) or {}
    lineas = []
    for k, n, u in [("cpu_temp", "Temperatura de CPU", "°C"), ("cpu_temp_max_core", "Núcleo más caliente", "°C"),
                    ("cpu_usage", "Uso de CPU", "%"),
                    ("ram_usage", "Uso de RAM", "%"), ("disk_free_gb", "Espacio libre en disco", "GB"),
                    ("disk_used_pct", "Disco usado", "%"), ("disk_temp_max", "Temperatura del disco", "°C"),
                    ("disk_life_min_pct", "Vida útil restante del disco", "%"),
                    ("gpu_temp", "Temperatura de GPU", "°C"), ("gpu_hotspot", "Punto más caliente de la GPU", "°C"),
                    ("gpu_load", "Uso de GPU", "%"), ("fan_max_rpm", "Ventilador del sistema más rápido", "RPM")]:
        if k in m:
            lineas.append(f"{n}: {m[k]} {u}")
    for k, n in [("cpu", "Procesador"), ("ram", "RAM instalada"),
                 ("storage", "Almacenamiento"), ("gpu", "Gráficos"), ("os", "Sistema operativo")]:
        if r.get(k):
            lineas.append(f"{n}: {r[k]}")
    return "\n".join(lineas) or "Sin datos medidos."


def _causas(result) -> str:
    causas = (result or {}).get("causes") or []
    if not causas:
        return "- Sin causas identificadas."
    return "\n".join(
        f"- {c['cause']} (prioridad {c['priority']}, confianza {c['confidence_label']}; "
        f"evidencia: {'; '.join(c['evidence'])})" for c in causas)


def analysis_messages(caso, scan, result) -> list[dict]:
    return _msgs(
        f"Equipo: {_g(caso, 'equipo')}\n"
        f"Problema reportado: {_g(caso, 'problem')}\n\n"
        f"Datos del equipo:\n{_datos_scan(scan)}\n\n"
        f"Posibles causas detectadas por el motor de reglas:\n{_causas(result)}\n\n"
        "Tarea: escribe un solo párrafo (máximo 90 palabras) que explique cómo se relacionan "
        "los síntomas y los datos con las causas más probables. No agregues causas nuevas. "
        "Termina indicando que el técnico debe validarlo con pruebas.")


def history_messages(caso, historial: list[dict]) -> list[dict]:
    lineas = "\n".join(
        f"- {h['fecha']} · {h['code']}: {h['problema']} · estado {h['estado']} · "
        f"causa: {h['causa'] or 'sin diagnóstico'}" for h in historial)
    return _msgs(
        f"Equipo: {_g(caso, 'equipo')} (serie {_g(caso, 'serial')})\n"
        f"Casos registrados, del más antiguo al más reciente:\n{lineas}\n\n"
        "Tarea: resume en máximo 80 palabras el historial de este equipo. Indica si algún "
        "problema se repite y qué convendría revisar en la visita actual.")


def client_messages(caso, result, negocio: str = "el taller") -> list[dict]:
    cliente = _g(caso, "cliente", "cliente")
    return _msgs(
        f"Cliente: {cliente}\nEquipo: {_g(caso, 'equipo')}\n"
        f"Problema reportado: {_g(caso, 'problem')}\n"
        f"Posibles causas:\n{_causas(result)}\n"
        f"Recomendaciones: {'; '.join((result or {}).get('recommendations', [])) or 'ninguna'}\n\n"
        f"Tarea: redacta un mensaje corto (máximo 100 palabras) para {cliente}, sin "
        "tecnicismos, que explique el problema probable y qué se recomienda hacer. "
        f"No prometas precios ni plazos. Cierra con un saludo de {negocio}.")


def relevant_rules(pregunta: str, reglas: list[dict], n: int = 3) -> list[dict]:
    palabras = {p for p in re.findall(r"[a-z0-9]{4,}", normalizar(pregunta)) if p not in _STOP}
    puntuadas = []
    for r in reglas:
        texto = normalizar(" ".join([
            r["cause"], r["category"],
            *[s["name"] + " " + " ".join(s["keywords"]) for s in r["symptoms"]],
            *r["recommendations"]]))
        puntaje = sum(1 for p in palabras if p in texto)
        if puntaje:
            puntuadas.append((puntaje, r))
    puntuadas.sort(key=lambda x: -x[0])
    return [r for _, r in puntuadas[:n]]


def support_messages(pregunta: str, reglas: list[dict]) -> list[dict]:
    if reglas:
        ctx = "\n".join(
            f"- {r['cause']} ({r['category']}). Síntomas: "
            f"{', '.join(s['name'] for s in r['symptoms'])}. "
            f"Recomendaciones: {'; '.join(r['recommendations'])}" for r in reglas)
    else:
        ctx = "(No hay reglas relacionadas en la base de conocimiento.)"
    return _msgs(
        f"Base de conocimiento del taller:\n{ctx}\n\nPregunta del técnico: {pregunta}\n\n"
        "Tarea: responde en máximo 120 palabras, con pasos concretos si corresponde. "
        "Apóyate en la base de conocimiento; si no alcanza, dilo.")


def test_messages() -> list[dict]:
    return [{"role": "user", "content": "Responde únicamente con la palabra: listo"}]
