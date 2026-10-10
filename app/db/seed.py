from app.paths import db_path
from .database import Database
from .repo import Repository

DEMO = [
    ("Luis Paredes", "987000111", "HP15-48213", "Laptop HP 15", "Arranque lento", "Media", "Entregado", "Reglas + IA local"),
    ("Ana Torres", "987000222", "DELL-77120", "PC Dell OptiPlex", "Bajo rendimiento", "Media", "Recibido", "Reglas"),
    ("Carlos Rojas", "987000333", "LEN-30955", "Laptop Lenovo", "Disco lleno", "Alta", "En diagnóstico", "Reglas + IA local"),
    ("Marta Díaz", "987000444", "ARM-55018", "PC armada", "RAM elevada", "Media", "Listo", "Reglas"),
]


def cargar_demo(repo: Repository) -> int:
    if repo.list_cases():
        return 0
    for cliente, tel, serie, equipo, problema, prio, estado, metodo in DEMO:
        cid = repo.add_client(cliente, tel)
        eid = repo.upsert_equipment(serie, equipo, cid)
        repo.create_case(eid, problema, prio, estado, metodo)
    return len(DEMO)


if __name__ == "__main__":
    db = Database(db_path())
    n = cargar_demo(Repository(db))
    print(f"Casos de ejemplo cargados: {n}")
    db.close()