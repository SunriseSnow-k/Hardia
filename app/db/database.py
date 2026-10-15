import functools
import sqlite3
from contextlib import contextmanager

from .migraciones import VERSION_ACTUAL as VERSION_ESQUEMA  # noqa: F401 (se reexporta)
from .migraciones import migrar


class Conexion(sqlite3.Connection):
    """Conexión con transacciones anidables.

    Dentro de `with conn.transaccion():` los `commit()` de los repositorios no confirman nada:
    todo se confirma junto al salir del bloque, o se deshace si ocurre un error. Los bloques
    anidados usan SAVEPOINT, así que un error en un paso opcional deshace solo ese paso.
    """

    _nivel = 0

    def commit(self):
        if self._nivel == 0:
            super().commit()

    @property
    def en_transaccion(self) -> bool:
        return self._nivel > 0

    @contextmanager
    def transaccion(self):
        punto = f"sp_{self._nivel}"
        self.execute(f"SAVEPOINT {punto}")
        self._nivel += 1
        try:
            yield self
        except BaseException:
            self._nivel -= 1
            self.execute(f"ROLLBACK TO {punto}")
            self.execute(f"RELEASE {punto}")
            raise
        self._nivel -= 1
        self.execute(f"RELEASE {punto}")
        if self._nivel == 0:
            super().commit()


def ultimo_id(cur: sqlite3.Cursor) -> int:
    """Id de la fila recién insertada (sqlite siempre lo informa tras un INSERT)."""
    if cur.lastrowid is None:
        raise RuntimeError("La inserción no devolvió un id.")
    return cur.lastrowid


def transaccional(metodo):
    """Ejecuta un método de repositorio (con atributo `c`) como una sola transacción."""
    @functools.wraps(metodo)
    def envoltura(self, *args, **kwargs):
        with self.c.transaccion():
            return metodo(self, *args, **kwargs)
    return envoltura


class Database:
    def __init__(self, path, carpeta_copias=None):
        """Abre la base y aplica las migraciones pendientes. Si se indica `carpeta_copias`,
        una base con datos se respalda allí antes de actualizar su esquema."""
        self.conn = sqlite3.connect(str(path), factory=Conexion)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self.migraciones_aplicadas = migrar(self.conn, carpeta_copias)
        except BaseException:
            self.conn.close()
            raise

    def close(self):
        self.conn.close()
