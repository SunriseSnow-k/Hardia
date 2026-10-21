#!/bin/sh
# Instala Sistema Inteligente Offline en Linux para el usuario actual (el programa no necesita sudo).
#   Programa:  ~/.local/opt/SistemaDiagnostico
#   Menú:      ~/.local/share/applications/sistemadiagnostico.desktop
#   Ícono:     ~/.local/share/icons/hicolor/256x256/apps/sistemadiagnostico.png
#   Comando:   ~/.local/bin/sistemadiagnostico
# Los datos (base de datos, reportes, copias, paquete de IA) viven en ~/.local/share/SistemaDiagnostico
# y no se tocan al actualizar ni al desinstalar.
# Uso:  sh instalar.sh                     (pregunta si instalar los paquetes recomendados)
#       sh instalar.sh --con-dependencias  (los instala sin preguntar; pide sudo)
#       sh instalar.sh --sin-dependencias  (no los instala ni pregunta)
set -e
ORIGEN=$(cd "$(dirname "$0")" && pwd)
DATOS="${XDG_DATA_HOME:-$HOME/.local/share}"
DESTINO="$HOME/.local/opt/SistemaDiagnostico"
MENU="$DATOS/applications"
ICONOS="$DATOS/icons/hicolor/256x256/apps"
BIN="$HOME/.local/bin"
DEPENDENCIAS=preguntar
for a in "$@"; do
    case "$a" in
        --con-dependencias) DEPENDENCIAS=si ;;
        --sin-dependencias) DEPENDENCIAS=no ;;
        *) echo "Opción desconocida: $a"; exit 2 ;;
    esac
done

# ¿Está abierto? Se mira el ejecutable real de cada proceso: el nombre se corta a 15 caracteres y
# la línea de comandos puede ser la del enlace ~/.local/bin/sistemadiagnostico
abierto() {
    [ -d "$DESTINO" ] || return 1
    exe="$(cd "$DESTINO" && pwd -P)/SistemaDiagnostico"
    for p in /proc/[0-9]*/exe; do
        case "$(readlink "$p" 2>/dev/null)" in "$exe"|"$exe (deleted)") return 0 ;; esac
    done
    return 1
}

if [ ! -x "$ORIGEN/SistemaDiagnostico/SistemaDiagnostico" ]; then
    if [ -f "$ORIGEN/SistemaDiagnostico/SistemaDiagnostico" ]; then
        chmod +x "$ORIGEN/SistemaDiagnostico/SistemaDiagnostico" 2>/dev/null || true
    fi
    if [ ! -x "$ORIGEN/SistemaDiagnostico/SistemaDiagnostico" ]; then
        echo "No se encontró el programa junto a este instalador (carpeta SistemaDiagnostico)."
        echo "Descomprima el paquete en una carpeta de Linux (no en una memoria FAT32 o NTFS) y vuelva a intentarlo."
        exit 1
    fi
fi
case "$(uname -m)" in
    x86_64|amd64) ;;
    *) echo "Este paquete es para Linux de 64 bits (x86_64); este equipo es $(uname -m)."; exit 1 ;;
esac
# El programa funciona con una glibc igual o más nueva que la del equipo donde se generó
if [ -f "$ORIGEN/glibc-minima.txt" ] && command -v ldd >/dev/null 2>&1; then
    MINIMA=$(cat "$ORIGEN/glibc-minima.txt")
    ACTUAL=$(ldd --version 2>/dev/null | head -n 1 | grep -oE '[0-9]+\.[0-9]+$' || true)
    if [ -n "$ACTUAL" ] && [ "$(printf '%s\n%s\n' "$MINIMA" "$ACTUAL" | sort -V | head -n 1)" != "$MINIMA" ]; then
        echo "Este paquete necesita glibc $MINIMA o más nueva y este equipo tiene $ACTUAL."
        echo "Actualice la distribución o genere el paquete con build.sh en una distribución más antigua."
        exit 1
    fi
fi
if abierto; then
    echo "El programa está abierto. Ciérrelo y vuelva a ejecutar el instalador."
    exit 1
fi

echo "Instalando en $DESTINO…"
mkdir -p "$(dirname "$DESTINO")" "$MENU" "$ICONOS" "$BIN"
rm -rf "$DESTINO.nuevo"
cp -r "$ORIGEN/SistemaDiagnostico" "$DESTINO.nuevo"
chmod +x "$DESTINO.nuevo/SistemaDiagnostico"
[ -f "$DESTINO.nuevo/Colector/Colector" ] && chmod +x "$DESTINO.nuevo/Colector/Colector"
# Comprobación: el programa copiado carga sus bibliotecas (si no, se conserva la versión anterior)
if ! "$DESTINO.nuevo/SistemaDiagnostico" --ayudante-root </dev/null 2>/dev/null | grep -q '"listo"'; then
    rm -rf "$DESTINO.nuevo"
    echo "El programa no pudo iniciarse en este equipo (faltan bibliotecas del sistema o la glibc es antigua)."
    exit 1
fi
rm -rf "$DESTINO"
mv "$DESTINO.nuevo" "$DESTINO"

cp "$DESTINO/_internal/app/assets/icono.png" "$ICONOS/sistemadiagnostico.png"
cat > "$MENU/sistemadiagnostico.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Sistema Inteligente Offline
GenericName=Diagnóstico de computadoras
Comment=Diagnóstico de computadoras para talleres de servicio técnico
Exec="$DESTINO/SistemaDiagnostico"
Icon=sistemadiagnostico
Terminal=false
Categories=System;Monitor;
Keywords=diagnóstico;hardware;taller;reparación;
StartupNotify=true
StartupWMClass=SistemaDiagnostico
EOF
ln -sf "$DESTINO/SistemaDiagnostico" "$BIN/sistemadiagnostico"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATOS/icons/hicolor" >/dev/null 2>&1 || true

echo "Listo. Abra «Sistema Inteligente Offline» desde el menú de aplicaciones"
echo "o escriba sistemadiagnostico en una terminal."
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "(La carpeta $BIN no está en el PATH: el comando estará disponible al volver a iniciar sesión.)" ;;
esac

# ---------------- paquetes del sistema recomendados ----------------
# Qt necesita libxcb-cursor en escritorios X11; los demás amplían lo que el escaneo puede leer
if command -v apt-get >/dev/null 2>&1; then
    GESTOR="apt-get install -y"; CURSOR=libxcb-cursor0; SENSORES=lm-sensors
elif command -v dnf >/dev/null 2>&1; then
    GESTOR="dnf install -y"; CURSOR=xcb-util-cursor; SENSORES=lm_sensors
elif command -v zypper >/dev/null 2>&1; then
    GESTOR="zypper --non-interactive install"; CURSOR=libxcb-cursor0; SENSORES=sensors
elif command -v pacman >/dev/null 2>&1; then
    GESTOR="pacman -S --needed --noconfirm"; CURSOR=xcb-util-cursor; SENSORES=lm_sensors
else
    GESTOR=""; CURSOR=libxcb-cursor0; SENSORES=lm-sensors
fi
falta=""
LDCONFIG=$(command -v ldconfig || { [ -x /sbin/ldconfig ] && echo /sbin/ldconfig; } || true)
if [ -n "$LDCONFIG" ] && ! "$LDCONFIG" -p 2>/dev/null | grep -q "libxcb-cursor.so.0"; then
    falta="$falta $CURSOR"
fi
for p in smartctl:smartmontools dmidecode:dmidecode lspci:pciutils "sensors:$SENSORES" pkexec:polkit; do
    programa=${p%%:*}
    command -v "$programa" >/dev/null 2>&1 || [ -x "/usr/sbin/$programa" ] || [ -x "/sbin/$programa" ] \
        || falta="$falta ${p#*:}"
done
[ -z "$falta" ] && exit 0

echo
echo "Recomendado: estos paquetes permiten leer todos los datos del hardware:$falta"
echo "  smartmontools: salud SMART, temperatura y vida útil de los discos · dmidecode: módulos de RAM"
echo "  pciutils: nombre de la tarjeta gráfica · sensores: temperatura de la CPU en algunos equipos"
echo "  polkit (pkexec): pedir la contraseña de administrador desde el programa · $CURSOR: Qt en X11"
if [ -z "$GESTOR" ]; then
    echo "Instálelos con el gestor de paquetes de su distribución."
    exit 0
fi
if [ "$DEPENDENCIAS" = preguntar ]; then
    if [ -t 0 ]; then
        printf "¿Instalarlos ahora? Se pedirá la contraseña de sudo [s/N]: "
        read -r r || r=""
        case "$r" in s|S|si|sí|Si|Sí) DEPENDENCIAS=si ;; *) DEPENDENCIAS=no ;; esac
    else
        DEPENDENCIAS=no
    fi
fi
if [ "$DEPENDENCIAS" = si ]; then
    [ "$GESTOR" = "apt-get install -y" ] && { sudo apt-get update -qq || true; }
    # shellcheck disable=SC2086  # $GESTOR y $falta son listas de palabras
    if sudo $GESTOR $falta; then
        echo "Paquetes instalados."
        command -v sensors-detect >/dev/null 2>&1 \
            && echo "Si la temperatura de la CPU no aparece, ejecute una vez: sudo sensors-detect --auto"
    else
        echo "No se pudieron instalar todos los paquetes; el programa funciona igual con menos datos."
    fi
else
    echo "Para instalarlos más tarde:  sudo $GESTOR$falta"
fi
