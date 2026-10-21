"""Fase 21: Linux sin abrir la interfaz como root. El ayudante con permisos (pkexec) entrega los datos
protegidos del escaneo y lee los discos para la prueba; el equipo local se reconoce sin root."""
import io
import json
import sys

import pytest

from app.hardware import ayudante_root, linux, permisos_linux
from app.hardware.inventory import FUERTES, FUERTES_LOCAL, identifiers_from_scan
from app.health import benchmark as bm
from tests.test_fase19_linux import LinuxSimulado

solo_linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="el ayudante usa select sobre tuberías")


# ---------------- ayudante (lo que corre como root) ----------------
def test_datos_del_ayudante_desde_un_sys_simulado(tmp_path, monkeypatch):
    dmi = tmp_path / "sys" / "class" / "dmi" / "id"
    dmi.mkdir(parents=True)
    (dmi / "product_serial").write_text("PF2ABCDE\n")
    (dmi / "product_uuid").write_text("4c4c4544-0042-4a10-8057-b8c04f4d3532\n")
    for n in ("nvme0n1", "sda", "loop0", "sr0", "mmcblk0boot0", "dm-0"):
        (tmp_path / "sys" / "block" / n).mkdir(parents=True)
    monkeypatch.setattr(ayudante_root, "ejecutar", lambda *a: f"salida de {' '.join(a)}")
    d = ayudante_root.datos(str(tmp_path))
    assert d["archivos"] == {"/sys/class/dmi/id/product_serial": "PF2ABCDE",
                             "/sys/class/dmi/id/product_uuid": "4c4c4544-0042-4a10-8057-b8c04f4d3532"}
    assert [c[0] for c in d["comandos"]] == [["dmidecode", "-t", "17"], ["smartctl", "-j", "-a", "/dev/nvme0n1"],
                                             ["smartctl", "-j", "-a", "/dev/sda"]]
    assert d["comandos"][1][1] == "salida de smartctl -j -a /dev/nvme0n1"


@pytest.mark.parametrize("ruta", ["/etc/shadow", "/dev/../etc/shadow", "/dev/loop0", "/dev/sda1x;rm", "", "/dev/"])
def test_el_ayudante_solo_lee_discos(ruta):
    assert not ayudante_root.es_disco(ruta)


def _atender(ordenes: list[dict], monkeypatch, lectura=None) -> list[dict]:
    if lectura is not None:
        monkeypatch.setattr(ayudante_root, "es_disco", lambda r: r == "/dev/sdz")
        monkeypatch.setattr(ayudante_root, "leer_dispositivo", lectura)
    monkeypatch.setattr(ayudante_root, "datos", lambda: {"tipo": "datos", "archivos": {}, "comandos": []})
    salida = io.StringIO()
    ayudante_root.atender(io.StringIO("".join(json.dumps(o) + "\n" for o in ordenes) + "basura\n"), salida)
    return [json.loads(l) for l in salida.getvalue().splitlines()]


def test_protocolo_del_ayudante(monkeypatch):
    def lectura(ruta, duracion, cancelado, al_avanzar):
        al_avanzar(0.5, 1_000_000)
        return {"lectura_mb_s": 2.0, "bytes": 1_000_000, "duracion_s": duracion, "estado": "ok", "motivo": ""}
    r = _atender([{"orden": "datos"}, {"orden": "leer_disco", "ruta": "/dev/sdz", "duracion": 9999},
                  {"orden": "leer_disco", "ruta": "/etc/passwd"}, {"orden": "fin"}, {"orden": "datos"}],
                 monkeypatch, lectura)
    assert [m["tipo"] for m in r] == ["listo", "datos", "avance", "resultado", "resultado"]
    assert r[3]["duracion_s"] == 600.0  # la duración pedida se limita
    assert r[4]["estado"] == "fallo" and "no es un disco" in r[4]["motivo"]


@solo_linux
def test_sesion_real_con_el_ayudante_sin_pkexec():
    """El mismo ayudante que lanza pkexec, como usuario normal: protocolo completo por tuberías."""
    with permisos_linux.SesionAdmin.abrir(orden=permisos_linux.orden_ayudante()) as s:
        d = s.datos()
        assert d["tipo"] == "datos" and isinstance(d["comandos"], list)
        r = s.leer_disco("/etc/passwd", 1)
        assert r["estado"] == "fallo" and r["lectura_mb_s"] is None
    assert s._proc is None


def test_pkexec_cancelado_o_ayudante_roto():
    with pytest.raises(permisos_linux.PermisoDenegado, match="canceló"):
        permisos_linux.SesionAdmin.abrir(orden=[sys.executable, "-c", "import sys; sys.exit(126)"])
    with pytest.raises(permisos_linux.PermisoDenegado, match="inesperada"):
        permisos_linux.SesionAdmin.abrir(orden=[sys.executable, "-c", "print('{\"tipo\": \"otro\"}')"])
    with pytest.raises(permisos_linux.PermisoDenegado):
        permisos_linux.SesionAdmin.abrir(orden=["/no/existe/pkexec"])


def test_orden_del_ayudante_empaquetado(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/SistemaDiagnostico/SistemaDiagnostico")
    assert permisos_linux.orden_ayudante() == ["/opt/SistemaDiagnostico/SistemaDiagnostico", "--ayudante-root"]


# ---------------- escaneo con los datos del ayudante ----------------
def test_entorno_linux_usa_los_datos_protegidos(monkeypatch):
    env = linux.EntornoLinux()
    monkeypatch.setattr(linux.plataforma, "es_administrador", lambda: False)
    assert not env.es_admin()
    env.usar_privilegiados({"archivos": {"/sys/class/dmi/id/product_serial": " PF2ABCDE \n", "x": 3},
                            "comandos": [[["dmidecode", "-t", "17"], "Memory Device"], [["smartctl"], None],
                                         "basura", [["a"]]]})
    assert env.es_admin()
    assert env.leer("/sys/class/dmi/id/product_serial") == "PF2ABCDE"
    assert env.ejecutar("dmidecode", "-t", "17") == "Memory Device" and env.ejecutar("smartctl") is None


def test_escaneo_con_permisos_desde_la_interfaz(monkeypatch):
    from app.hardware import scanner
    sim = LinuxSimulado(root=False)

    class Entorno(linux.EntornoLinux):  # el Linux simulado, con la capa de datos protegidos real
        def __init__(self):
            super().__init__()
            self.psutil = sim.psutil

        def leer(self, ruta):
            return self._archivos.get(ruta, sim.leer(ruta))

        def ejecutar(self, *args):
            return self._cache[args] if args in self._cache else sim.ejecutar(*args)

        def es_admin(self):
            return self._privilegiado

    for nombre in ("leer_bytes", "listar", "existe", "ruta_real", "tiene", "hostname", "machine", "processor",
                   "release"):
        monkeypatch.setattr(Entorno, nombre, staticmethod(getattr(sim, nombre)))
    monkeypatch.setattr(scanner, "_crear_entorno", Entorno)
    sin = scanner.run_scan()
    assert sin["inventory"]["memory"]["modules"] == []
    from tests.test_fase19_linux import COMANDOS
    datos = {"archivos": {}, "comandos": [[list(k), v] for k, v in COMANDOS.items() if k[0] != "lspci"]}
    con = scanner.run_scan(privilegiados=datos)
    assert len(con["inventory"]["memory"]["modules"]) == 1
    assert con["inventory"]["storage"]["physical"][0]["health"] == "Saludable"
    faltan = [f["campo"] for c in con["availability"].values() for f in c["faltantes"]]
    assert "Módulos individuales" not in faltan


def test_fabricante_del_disco_y_rpm():
    assert linux._marca_disco("ATA", "ST1000LM035-1RK1") == "Seagate"
    assert linux._marca_disco("", "WD Green SN350 500GB") == "Western Digital"
    assert linux._marca_disco("ATA", "XYZ 123", "Samsung based SSDs") == "Samsung"
    assert linux._marca_disco("Kingston", "SA400S37") == "Kingston"
    assert linux._marca_disco("ATA", "Desconocido") == ""
    env = LinuxSimulado(comandos={("smartctl", "-j", "-a", "/dev/nvme0n1"):
                                  json.dumps({"rotation_rate": 5400, "model_family": "Seagate Mobile HDD"})})
    assert linux._smart(env, "/dev/nvme0n1")["rpm"] == 5400


# ---------------- reconocer este equipo sin root ----------------
def test_identificador_de_la_instalacion_sin_root():
    env = LinuxSimulado(root=False, archivos={"/etc/machine-id": "d299694db360c81b679fee796ac10323\n"})
    mid = linux._identidad(env)["data"]["machine_id"]
    assert len(mid) == 32 and mid != "D299694DB360C81B679FEE796AC10323"  # no se guarda el valor original
    assert linux._id_maquina(LinuxSimulado(archivos={"/etc/machine-id": "no-valido"})) == ""
    ids = identifiers_from_scan({"inventory": {"identity": {"machine_id": mid}}})
    assert ids == [("machine_id", mid)]
    assert "machine_id" in FUERTES_LOCAL and "machine_id" not in FUERTES


def test_misma_maquina_y_caso_con_el_identificador_de_linux(tmp_path):
    from app.db.database import Database
    from app.db.hardware_repo import HardwareRepository
    from app.db.repo import Repository
    from app.ui.pages.salud import misma_maquina
    captura = {"inventory": {"identity": {"machine_id": "AB" * 16}}}
    assert misma_maquina(captura, [("machine_id", "AB" * 16)]) is True
    assert misma_maquina(captura, [("machine_id", "CD" * 16)]) is False
    db = Database(tmp_path / "t.db")
    repo = Repository(db)
    hr = HardwareRepository(repo)
    eq = repo.equipment_id_of_case(repo.register_intake("Luis", "1", "", "Laptop", "Lento"))
    hr.add_identifiers(eq, [("machine_id", "AB" * 16)])
    assert hr.identify([("machine_id", "AB" * 16)])["status"] == "probable"  # no reconoce equipos de clientes
    assert hr.identify([("machine_id", "AB" * 16)], fuertes=FUERTES_LOCAL)["equipment_id"] == eq
    db.close()


# ---------------- prueba de discos con la sesión ----------------
def test_prueba_de_discos_con_la_sesion(monkeypatch, tmp_path):
    if sys.platform == "win32":
        pytest.skip("en Windows la prueba usa la API de Windows")
    sin_permiso = tmp_path / "disco"
    sin_permiso.write_bytes(b"x")
    sin_permiso.chmod(0)

    class Sesion:
        def leer_disco(self, ruta, duracion, cancelado, al_avanzar):
            al_avanzar(0.5, 10)
            return {"lectura_mb_s": 500.0, "bytes": 10, "duracion_s": duracion, "estado": "ok", "motivo": ""}
    avances = []
    r = bm.lectura_disco(0, 3, ruta=str(sin_permiso), sesion=Sesion(), al_avanzar=lambda t, b: avances.append(b))
    assert r["lectura_mb_s"] == 500.0 and r["index"] == 0 and avances == [10]
    assert permisos_linux.sesion_si_hace_falta([None, "/etc/hostname"]) == (None, None)


# ---------------- interfaz ----------------
def test_boton_escanear_con_permisos(monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton
    QApplication.instance() or QApplication([])
    from app.hardware import lhm
    from app.ui.pages import escaneo
    monkeypatch.setattr(lhm, "puede_pedir_permisos", lambda: True)
    monkeypatch.setattr(lhm, "requisitos_sensores", lambda: ["escanear con permisos de administrador"])
    pedidos = []
    monkeypatch.setattr(permisos_linux, "datos_protegidos", lambda: pedidos.append(1) or (None, "se canceló"))
    usados = []

    def escaneo_simulado(progress=None, privilegiados=None):
        usados.append(privilegiados)
        return {"components": [], "metrics": {}, "summary": {}}
    monkeypatch.setattr(escaneo, "run_scan", escaneo_simulado)
    pagina = escaneo.EscaneoPage()
    boton = [b for b in pagina.aviso_sensores.findChildren(QPushButton) if b.text() == "Escanear con permisos"]
    assert len(boton) == 1 and pagina.b_scan_admin is boton[0]
    boton[0].click()
    assert pagina.worker.wait(5000)
    QApplication.processEvents()
    assert pedidos == [1] and usados == [None]  # sin contraseña se escanea igual, sin los datos protegidos
    assert "sin permisos de administrador: se canceló" in pagina.msg.text()
    assert pagina.b_scan_admin.isEnabled() and pagina.b_scan.isEnabled()


def test_sin_pkexec_no_hay_boton(monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.hardware import lhm
    from app.ui.pages import escaneo
    monkeypatch.setattr(lhm, "puede_pedir_permisos", lambda: False)
    assert escaneo.EscaneoPage().b_scan_admin is None
