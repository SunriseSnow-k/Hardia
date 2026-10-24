"""Registro de auditoría: quién hizo cada acción sensible y cuándo. Solo se agregan filas;
el programa no ofrece forma de editarlas ni borrarlas."""
import sqlite3

from .repo import QAKM_Repository

ACCIONES = {
    "sesion_iniciada": "Inicio de sesión",
    "sesion_fallida": "Intento de acceso fallido",
    "cuenta_bloqueada": "Cuenta bloqueada por intentos fallidos",
    "usuario_creado": "Técnico creado",
    "contrasena_cambiada": "Contraseña cambiada",
    "contrasena_restablecida": "Contraseña restablecida por un administrador",
    "rol_cambiado": "Rol cambiado",
    "usuario_desactivado": "Técnico desactivado",
    "usuario_activado": "Técnico reactivado",
    "copia_creada": "Copia de seguridad creada",
    "copia_restaurada": "Copia de seguridad restaurada",
    "taller_actualizado": "Datos del taller actualizados",
    "presupuesto_aprobado": "Presupuesto aprobado",
    "presupuesto_rechazado": "Presupuesto rechazado",
    "presupuesto_reabierto": "Presupuesto reabierto",
    "pago_registrado": "Pago registrado",
    "pago_anulado": "Pago anulado",
}


class QAKM_AuditRepository:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, repo: QAKM_Repository):
        self.c = repo.c

    def registrar(self, accion: str, tech_id: str = "", detalle: str = "") -> None:
        if accion not in ACCIONES:
            raise ValueError(f"Acción de auditoría desconocida: {accion}")
        self.c.execute("INSERT INTO audit_log(tech_id, action, detail) VALUES (?,?,?)",
                       ((tech_id or "").strip().upper(), accion, (detalle or "")[:500]))
        self.c.commit()

    def recientes(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.c.execute("SELECT id, at, tech_id, action, detail FROM audit_log "
                              "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
