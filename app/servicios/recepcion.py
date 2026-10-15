"""Registro de la recepción de un equipo: cliente, equipo, caso, documento, captura de hardware,
salud y orden de servicio, en una sola transacción.

Si falla un paso obligatorio (cliente, equipo o caso) no se guarda nada. Los pasos opcionales
(documento, captura, salud, orden) van en su propio punto de guardado: si uno falla se deshace
solo ese paso y se devuelve un aviso, sin perder la recepción.
"""
import logging
from dataclasses import dataclass, field
from datetime import date

from app.db.clients_repo import ClientsRepository, normalize_doc
from app.db.hardware_repo import HardwareRepository
from app.db.health_repo import HealthRepository
from app.db.orders_repo import OrdersRepository
from app.db.repo import Repository

log = logging.getLogger(__name__)


@dataclass
class DatosRecepcion:
    cliente: str
    equipo: str
    serie: str
    problema: str
    telefono: str = ""
    documento: str = ""
    prioridad: str = "Media"
    accesorios: list[str] = field(default_factory=list)
    estado_fisico: str = ""
    observaciones: str = ""
    fecha_estimada: str = ""  # AAAA-MM-DD o vacío
    tecnico: str = ""


@dataclass
class ResultadoRecepcion:
    code: str
    avisos: list[str] = field(default_factory=list)
    orden_guardada: bool = False


def validar(d: DatosRecepcion) -> str:
    """Comprueba los datos antes de escribir nada. Devuelve el documento normalizado."""
    if not all(v.strip() for v in (d.cliente, d.equipo, d.serie, d.problema)):
        raise ValueError("Complete cliente, equipo, serie y problema.")
    documento = normalize_doc(d.documento)
    if d.fecha_estimada:
        try:
            fecha = date.fromisoformat(d.fecha_estimada)
        except ValueError:
            raise ValueError("La fecha estimada de entrega no es válida.") from None
        if fecha < date.today():
            raise ValueError("La fecha estimada de entrega no puede ser anterior a hoy.")
    return documento


def registrar(repo: Repository, d: DatosRecepcion, hw: dict | None = None) -> ResultadoRecepcion:
    documento = validar(d)
    avisos: list[str] = []

    def opcional(descripcion: str, paso):
        try:
            with repo.transaccion():
                return paso()
        except Exception as e:  # el caso sigue registrado; solo se avisa
            log.exception("Recepción: falló %s", descripcion)
            avisos.append(f"No se pudo {descripcion} ({e}).")
            return None

    with repo.transaccion():
        code = repo.register_intake(d.cliente, d.telefono, d.serie, d.equipo, d.problema.strip(), d.prioridad)
        if documento:
            opcional("guardar el documento", lambda: ClientsRepository(repo).set_doc_for_case(code, documento))
        if hw:
            def captura():
                r: dict = hw["summary"] if isinstance(hw.get("summary"), dict) else {}
                cid = repo.add_client(d.cliente.strip(), d.telefono.strip())
                repo.upsert_equipment(d.serie, d.equipo.strip(), cid, cpu=r.get("cpu", ""), ram=r.get("ram", ""),
                                      storage=r.get("storage", ""), os_name=r.get("os", ""))
                return HardwareRepository(repo).save_capture(code, hw)

            res = opcional("guardar la captura de hardware", captura)
            if res and res["conflicts"]:
                avisos.append(f"{len(res['conflicts'])} identificador(es) del escaneo ya pertenecen a otro equipo "
                              "y no se reasignaron; revise que la serie sea la correcta.")
            if res:  # deja guardado el índice de salud para Equipos, Caso y futuros reingresos
                opcional("evaluar la salud del equipo", lambda: HealthRepository(repo).evaluate_case(code))
        def orden_de_servicio() -> bool:
            OrdersRepository(repo).save(code, d.accesorios, d.estado_fisico, d.observaciones,
                                        d.fecha_estimada, d.tecnico)
            return True

        orden = opcional("guardar la orden de servicio", orden_de_servicio)
    return ResultadoRecepcion(code, avisos, orden_guardada=bool(orden))
