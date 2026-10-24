"""Orden de servicio (PDF): comprobante de recepción que firma el cliente."""

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Spacer, Table, TableStyle

from app.db.clients_repo import QAKM_ClientsRepository
from app.db.orders_repo import QAKM_OrdersRepository

from . import base
from .base import TEXTO, _fecha, _kv, _p, _styles


def load_order_data(repo, code: str) -> dict:
    """Datos de la orden de servicio: solo lo registrado en la recepción (sin diagnóstico)."""
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    orders = QAKM_OrdersRepository(repo)
    orden = orders.get(code)
    return {
        "caso": caso, "doc_id": QAKM_ClientsRepository(repo).doc_for_case(code),
        "order": dict(orden) if orden else {}, "terms": orders.terms(),
        "business": repo.get_setting("business_name", "Mi taller"),
        "phone": repo.get_setting("business_phone", ""),
    }


def _firmas(izquierda: str, derecha: str, st) -> Table:
    centrado = ParagraphStyle("firma", parent=st["small"], alignment=1)
    t = Table([["", "", ""], [_p(izquierda, centrado), "", _p(derecha, centrado)]],
              colWidths=[75 * mm, 20 * mm, 75 * mm], rowHeights=[16 * mm, None])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (0, 0), 0.6, TEXTO), ("LINEBELOW", (2, 0), (2, 0), 0.6, TEXTO),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_order(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, orden = data["caso"], data["order"]
    contacto = data["business"] + (f' · Teléfono: {data["phone"]}' if data["phone"] else "")
    estimada = _fecha(orden["estimated_date"], 10) if orden.get("estimated_date") else "Por confirmar"
    story = [
        _p(contacto, st["biz"]), _p("Orden de servicio", st["h1"]), Spacer(1, 4 * mm),
        _kv([("N.º de orden", caso["code"]), ("Fecha de ingreso", _fecha(caso["created_at"])),
             ("Entrega estimada", estimada)], st),
    ]
    story.append(_p("Cliente", st["h2"]))
    story.append(_kv([("Nombre", caso["cliente"]), ("Documento", data["doc_id"]),
                      ("Teléfono", caso["phone"])], st))
    story.append(_p("Equipo recibido", st["h2"]))
    story.append(_kv([("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"]),
                      ("Accesorios", orden.get("accessories") or "Ninguno"),
                      ("Estado físico", orden.get("condition") or "Sin observaciones")], st))
    story.append(_p("Problema reportado por el cliente", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))
    if orden.get("observations"):
        story.append(_p("Observaciones de la recepción", st["h2"]))
        story.append(_p(orden["observations"], st["body"]))
    if data["terms"]:
        story.append(_p("Condiciones del servicio", st["h2"]))
        for i, t in enumerate(data["terms"], 1):
            story.append(_p(f"{i}. {t}", st["cell"]))
    recibido = orden.get("received_by") or tech_id or ""
    story.append(Spacer(1, 8 * mm))
    story.append(KeepTogether([
        _p("Con su firma, el cliente declara que entrega el equipo en el estado descrito y acepta las "
           "condiciones del servicio.", st["small"]),
        Spacer(1, 4 * mm),
        _firmas("Firma del cliente", f"Recibido por{': ' + recibido if recibido else ''}", st),
    ]))
    base._construir(story, path, f'Orden de servicio {caso["code"]}', tech_id, caso["code"])
