#!/usr/bin/env bash
#
# Prepara la carpeta portable de PDFx para Linux, de principio a fin.
#
# Es el gemelo de build/setup-pdfx-windows.ps1: los mismos 7 pasos, los mismos
# mensajes y la misma autoprueba final. No hay que ejecutar nada mas ni tocar
# nada a mano.
#
#   ./INSTALAR_PDFx.sh                (o: bash INSTALAR_PDFx.sh)
#
# Para el desarrollador:
#   --solo-ocr       descarga el OCR y para
#   --solo-compilar  salta la descarga del OCR
#   --sin-prueba     no ejecuta la prueba de conversion final
#   --auto           sin preguntas ni pausas
#
# Todo el fichero es ASCII puro y sin tildes a proposito, igual que el de
# Windows: no se puede dar por hecha la configuracion regional del terminal.

set -uo pipefail

SOLO_OCR=0
SOLO_COMPILAR=0
SIN_PRUEBA=0
AUTO=0
for arg in "$@"; do
    case "$arg" in
        --solo-ocr)       SOLO_OCR=1 ;;
        --solo-compilar)  SOLO_COMPILAR=1 ;;
        --sin-prueba)     SIN_PRUEBA=1 ;;
        --auto)           AUTO=1 ;;
        -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "  Opcion desconocida: $arg"; exit 2 ;;
    esac
done
[ "$SOLO_OCR" = 1 ] && SOLO_COMPILAR=0

# ---------------------------------------------------------------- utilidades

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ" || { echo "  No encuentro la carpeta del proyecto."; exit 1; }
if [ ! -d "$RAIZ/pdfx" ]; then
    echo ""
    echo "  No encuentro la carpeta del proyecto (falta pdfx/)."
    echo "  Ejecuta el instalador desde la carpeta del proyecto:"
    echo "    ./INSTALAR_PDFx.sh"
    echo ""
    exit 1
fi

CARPETA_LOGS="$RAIZ/build"
REGISTRO="$CARPETA_LOGS/registro-instalacion-linux.txt"
AVISOS=()

# Cada plataforma deja lo suyo en su propia carpeta. Windows y Linux se
# construyen desde el mismo proyecto, asi que si los dos escribieran en
# dist/PDFx, .venv y build/build, compilar para uno borraria el portable del
# otro. Lo que si se comparte es lo que importa: el codigo, el .spec, las
# pruebas y los requisitos.
DIST_PLATAFORMA="$RAIZ/dist/linux"
PORTABLE="$DIST_PLATAFORMA/PDFx"
TRABAJO_PY="$RAIZ/build/build-linux"

# Color solo si la salida es un terminal de verdad; si se redirige a un
# fichero, los codigos de escape solo estorban.
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    C_CYAN=$'\033[36m'; C_VERDE=$'\033[32m'; C_AMAR=$'\033[33m'
    C_ROJO=$'\033[31m'; C_GRIS=$'\033[90m'; C_FIN=$'\033[0m'
else
    C_CYAN=''; C_VERDE=''; C_AMAR=''; C_ROJO=''; C_GRIS=''; C_FIN=''
fi

registro() { printf '%s\n' "$*" >> "$REGISTRO" 2>/dev/null || true; }

pausar() {
    [ "$AUTO" = 1 ] && return 0
    [ -t 0 ] || return 0
    echo ""
    read -r -p "  Pulsa Intro para cerrar" _ || true
}

paso()    { echo ""; echo "  ${C_CYAN}$*${C_FIN}"; registro ""; registro "=== $* ==="; }
bien()    { echo "     ${C_VERDE}[OK] $*${C_FIN}"; registro "[OK] $*"; }
aviso()   { echo "     ${C_AMAR}[!]  $*${C_FIN}"; registro "[!] $*"; AVISOS+=("$*"); }
detalle() { echo "          ${C_GRIS}$*${C_FIN}"; }

fallar() {
    local paso_fallo="$1" motivo="$2" log="$3"; shift 3
    echo ""
    echo "  ${C_ROJO}--------------------------------------------------------${C_FIN}"
    echo "  ${C_ROJO}   HA FALLADO. PDFx no se ha podido preparar.${C_FIN}"
    echo "  ${C_ROJO}--------------------------------------------------------${C_FIN}"
    echo ""
    echo "     Paso que fallo : $paso_fallo"
    echo "     Motivo         : $motivo"
    registro "FALLO en $paso_fallo : $motivo"
    if [ "$#" -gt 0 ]; then
        echo ""
        echo "     Que puedes hacer:"
        for c in "$@"; do echo "       - $c"; done
    fi
    if [ -n "$log" ] && [ -f "$log" ]; then
        echo ""
        echo "     Ultimas lineas del detalle tecnico:"
        tail -n 25 "$log" | while IFS= read -r l; do echo "       ${C_GRIS}${l}${C_FIN}"; done
    fi
    echo ""
    echo "     Si vuelve a fallar, envia este fichero a quien te dio el programa:"
    echo "       $REGISTRO"
    echo ""
    pausar
    exit 1
}

# Ejecuta un programa mostrando su salida segun llega y devolviendo su codigo.
# Se usa PIPESTATUS porque el codigo que interesa es el del primer eslabon de
# la tuberia, no el del sed que solo sangra las lineas.
ejecutar() {
    local log="$1"; shift
    registro "> $*"
    if [ -n "$log" ]; then
        "$@" 2>&1 | tee -a "$log" | sed "s/^/          ${C_GRIS}/;s/\$/${C_FIN}/"
    else
        "$@" 2>&1 | sed "s/^/          ${C_GRIS}/;s/\$/${C_FIN}/"
    fi
    return "${PIPESTATUS[0]}"
}

# Descarga probando varias fuentes y, si ninguna responde, repite la vuelta
# entera tras una espera corta. Un corte de red de unos segundos no deberia
# echar por tierra una instalacion de quince minutos.
descargar() {
    local destino="$1" minimo="$2"; shift 2
    local urls=("$@") motivos=() ronda url rc n
    for ronda in 1 2; do
        for url in "${urls[@]}"; do
            registro "descargando $url"
            rm -f "$destino"
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 30 \
                     --max-time 1800 -o "$destino" "$url" >>"$REGISTRO" 2>&1
                rc=$?
            elif command -v wget >/dev/null 2>&1; then
                wget -q -O "$destino" "$url" >>"$REGISTRO" 2>&1
                rc=$?
            else
                echo "no hay ni curl ni wget en el sistema"
                return 1
            fi
            n=0
            [ -f "$destino" ] && n=$(stat -c '%s' "$destino" 2>/dev/null || echo 0)
            if [ "$rc" = 0 ] && [ "$n" -ge "$minimo" ]; then
                return 0
            fi
            motivos+=("$url fallo (codigo $rc, $n bytes)")
        done
        if [ "$ronda" = 1 ]; then
            detalle "No ha entrado la descarga. Espero 15 segundos y lo intento otra vez..."
            registro "  ninguna fuente respondio: segunda ronda tras 15 s"
            sleep 15
        fi
    done
    rm -f "$destino"
    printf '%s' "${motivos[*]}"
    return 1
}

escribir_texto() {
    local ruta="$1"; shift
    printf '%s\n' "$@" > "$ruta"
}

# ---------------------------------------------------------------- cabecera

mkdir -p "$CARPETA_LOGS"
printf 'PDFx - instalacion iniciada %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" > "$REGISTRO"

echo ""
echo "  ${C_CYAN}========================================================${C_FIN}"
echo "  ${C_CYAN}   PDFx - preparar la carpeta portable para el USB${C_FIN}"
echo "  ${C_CYAN}========================================================${C_FIN}"
echo ""
echo "     Esto tarda entre 10 y 25 minutos segun tu conexion."
echo "     Veras pasar muchas lineas de texto: es normal."
echo "     No cierres esta ventana hasta que ponga LISTO."

# ---------------------------------------------------------------- 1. equipo

paso '[1 de 7] Comprobando el equipo'

ARQ="$(uname -m)"
registro "arquitectura: $ARQ"
if [ "$ARQ" != "x86_64" ]; then
    fallar '1 de 7 - comprobar el equipo' \
           "esta maquina es $ARQ y el OCR portable solo existe para x86_64" '' \
           'PDFx se puede compilar igual, pero sin OCR los PDF escaneados saldran vacios.' \
           'Instala tesseract con el gestor de paquetes de tu distribucion y usa --solo-compilar.'
fi

LIBRES_KB="$(df -Pk "$RAIZ" | awk 'NR==2 {print $4}')"
LIBRES_GB="$(awk -v k="$LIBRES_KB" 'BEGIN{printf "%.1f", k/1048576}')"
if awk -v k="$LIBRES_KB" 'BEGIN{exit !(k < 3145728)}'; then
    fallar '1 de 7 - comprobar el equipo' "solo quedan $LIBRES_GB GB libres y hacen falta 3" '' \
           'Libera espacio en el disco y vuelve a ejecutar el instalador.'
fi
bien "Espacio libre: $LIBRES_GB GB"

if [ -s /etc/os-release ]; then
    # shellcheck disable=SC1091
    DISTRO="$(. /etc/os-release; echo "${PRETTY_NAME:-$NAME}")"
    bien "Sistema: $DISTRO"
    registro "distro: $DISTRO"
fi

if command -v curl >/dev/null 2>&1; then
    if curl -fsS --head --max-time 20 https://pypi.org >/dev/null 2>&1; then
        bien 'Conexion a internet'
    else
        aviso 'No he podido comprobar la conexion. Si falla una descarga, ese es el motivo.'
    fi
fi

# ---------------------------------------------------------------- 2. Python

paso '[2 de 7] Buscando Python'

PYTHON=''
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
            PYTHON="$(command -v "$cand")"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    fallar '2 de 7 - buscar Python' 'no hay Python 3.10 o superior en este equipo' '' \
           'Instalalo con el gestor de paquetes de tu distribucion, por ejemplo:' \
           '  sudo apt install python3 python3-venv python3-tk   (Debian/Ubuntu)' \
           '  sudo dnf install python3 python3-tkinter           (Fedora)' \
           'y vuelve a ejecutar el instalador.'
fi
bien "Python $("$PYTHON" -c 'import platform; print(platform.python_version())')"
registro "python: $PYTHON"

# En Linux, a diferencia de Windows, Python viene troceado en paquetes. Sin
# ensurepip no se puede crear el entorno, y sin tkinter no hay ventana ni
# compilacion. Se detecta que falta y se instala solo; si no se puede, se dice
# exactamente que orden hay que teclear.
FALTAN_MOD=()
"$PYTHON" -c 'import ensurepip' >/dev/null 2>&1 || FALTAN_MOD+=('venv')
"$PYTHON" -c 'import tkinter'   >/dev/null 2>&1 || FALTAN_MOD+=('tk')
command -v objdump >/dev/null 2>&1                || FALTAN_MOD+=('binutils')

if [ "${#FALTAN_MOD[@]}" -gt 0 ]; then
    registro "faltan piezas del sistema: ${FALTAN_MOD[*]}"
    GESTOR=''; PAQUETES=()
    if command -v apt-get >/dev/null 2>&1; then
        GESTOR='apt-get'
        for m in "${FALTAN_MOD[@]}"; do
            case "$m" in
                venv)     PAQUETES+=('python3-venv') ;;
                tk)       PAQUETES+=('python3-tk') ;;
                binutils) PAQUETES+=('binutils') ;;
            esac
        done
    elif command -v dnf >/dev/null 2>&1; then
        GESTOR='dnf'
        for m in "${FALTAN_MOD[@]}"; do
            case "$m" in
                tk)       PAQUETES+=('python3-tkinter') ;;
                binutils) PAQUETES+=('binutils') ;;
            esac
        done
    elif command -v pacman >/dev/null 2>&1; then
        GESTOR='pacman'
        for m in "${FALTAN_MOD[@]}"; do
            case "$m" in
                tk)       PAQUETES+=('tk') ;;
                binutils) PAQUETES+=('binutils') ;;
            esac
        done
    elif command -v zypper >/dev/null 2>&1; then
        GESTOR='zypper'
        for m in "${FALTAN_MOD[@]}"; do
            case "$m" in
                tk)       PAQUETES+=('python3-tk') ;;
                binutils) PAQUETES+=('binutils') ;;
            esac
        done
    fi

    ORDEN=''
    case "$GESTOR" in
        apt-get) ORDEN="sudo apt-get install -y ${PAQUETES[*]}" ;;
        dnf)     ORDEN="sudo dnf install -y ${PAQUETES[*]}" ;;
        pacman)  ORDEN="sudo pacman -S --needed --noconfirm ${PAQUETES[*]}" ;;
        zypper)  ORDEN="sudo zypper install -y ${PAQUETES[*]}" ;;
    esac

    if [ -z "$ORDEN" ] || [ "${#PAQUETES[@]}" = 0 ]; then
        fallar '2 de 7 - buscar Python' "faltan piezas de Python: ${FALTAN_MOD[*]}" '' \
               'Instala el modulo venv, tkinter y binutils con el gestor de tu distribucion.'
    fi

    detalle "Faltan piezas del sistema: ${PAQUETES[*]}"
    if [ "$(id -u)" = 0 ]; then
        detalle "Instalandolas..."
        # shellcheck disable=SC2086
        ORDEN_ROOT="${ORDEN#sudo }"
        [ "$GESTOR" = 'apt-get' ] && ejecutar "$REGISTRO" apt-get update -qq
        ejecutar "$REGISTRO" $ORDEN_ROOT
    elif command -v sudo >/dev/null 2>&1; then
        echo ""
        echo "     Hacen falta estos paquetes del sistema: ${PAQUETES[*]}"
        echo "     Voy a instalarlos. Puede que te pida tu contrasena."
        echo ""
        [ "$GESTOR" = 'apt-get' ] && ejecutar "$REGISTRO" sudo apt-get update -qq
        # shellcheck disable=SC2086
        ejecutar "$REGISTRO" $ORDEN
    else
        fallar '2 de 7 - buscar Python' "faltan piezas de Python: ${FALTAN_MOD[*]}" '' \
               'No hay sudo en este equipo. Pide que instalen esto y repite:' \
               "  $ORDEN"
    fi

    PENDIENTE=()
    "$PYTHON" -c 'import ensurepip' >/dev/null 2>&1 || PENDIENTE+=('venv')
    "$PYTHON" -c 'import tkinter'   >/dev/null 2>&1 || PENDIENTE+=('tkinter')
    command -v objdump >/dev/null 2>&1                || PENDIENTE+=('binutils')
    if [ "${#PENDIENTE[@]}" -gt 0 ]; then
        fallar '2 de 7 - buscar Python' "sigue faltando: ${PENDIENTE[*]}" "$REGISTRO" \
               'Instalalo a mano y vuelve a ejecutar el instalador:' \
               "  $ORDEN"
    fi
    bien 'Piezas del sistema instaladas'
else
    bien 'Python trae venv, tkinter y binutils'
fi

# ---------------------------------------------------------- 3. componentes

paso '[3 de 7] Instalando componentes (unos 150 MB, tarda unos 5 minutos)'

VENV="$RAIZ/.venv-linux"
PY_VENV="$VENV/bin/python"
LOG_PIP="$CARPETA_LOGS/log-pip-linux.txt"
rm -f "$LOG_PIP"

if [ -x "$PY_VENV" ]; then
    bien 'Entorno .venv-linux ya existente'
else
    if ! ejecutar "$LOG_PIP" "$PYTHON" -m venv "$VENV"; then
        fallar '3 de 7 - instalar componentes' 'no se pudo crear el entorno .venv-linux' "$LOG_PIP" \
               'Comprueba que tienes el paquete python3-venv instalado.'
    fi
    bien 'Entorno .venv-linux creado'
fi

ejecutar "$LOG_PIP" "$PY_VENV" -m pip install --upgrade pip
if ! ejecutar "$LOG_PIP" "$PY_VENV" -m pip install -r "$RAIZ/requirements-dev.txt"; then
    fallar '3 de 7 - instalar componentes' 'pip no pudo instalar las dependencias' "$LOG_PIP" \
           'Suele ser un corte de red. Vuelve a ejecutar el instalador.' \
           'Lo que ya estaba instalado no se repite.'
fi
if ! ejecutar "$LOG_PIP" "$PY_VENV" -m PyInstaller --version; then
    fallar '3 de 7 - instalar componentes' 'PyInstaller no quedo instalado' "$LOG_PIP" \
           'Revisa el log de pip.'
fi
bien 'Componentes instalados'

# ------------------------------------------------------------- 4. Tesseract

TESS_DIR="$RAIZ/tools/tesseract-linux"
TESS_SH="$TESS_DIR/tesseract.sh"
IDIOMAS=(spa eng osd)

faltan_idiomas() {
    local f=() l
    for l in "${IDIOMAS[@]}"; do
        [ -f "$TESS_DIR/tessdata/$l.traineddata" ] || f+=("$l")
    done
    printf '%s' "${f[*]}"
}

if [ "$SOLO_COMPILAR" = 1 ]; then
    paso '[4 de 7] Descarga del OCR omitida (--solo-compilar)'
else
    paso '[4 de 7] Descargando el OCR Tesseract (unos 60 MB, tarda unos 2 minutos)'

    if [ -x "$TESS_SH" ] && [ -z "$(faltan_idiomas)" ]; then
        bien 'El OCR ya estaba descargado y completo'
    else
        # Igual que en Windows: la version se fija, pero se prueban varias por
        # si el empaquetador retira una release.
        VERSIONES=("${TESSERACT_VERSION:-5.5.1}" 5.5.0 5.4.1)
        APPIMAGE=''
        # Via de escape: si la red bloquea github, se puede dejar el AppImage
        # descargado en otro equipo dentro de tools/.
        for cand in "$RAIZ"/tools/tesseract-*.AppImage "$RAIZ"/tesseract-*.AppImage; do
            if [ -f "$cand" ] && [ "$(stat -c '%s' "$cand")" -gt 30000000 ]; then
                APPIMAGE="$cand"
                bien "Usando el AppImage que ya habias dejado en $cand"
                break
            fi
        done

        TMP_TESS="$(mktemp -d)"
        trap 'rm -rf "$TMP_TESS"' EXIT

        if [ -z "$APPIMAGE" ]; then
            URLS=()
            for v in "${VERSIONES[@]}"; do
                URLS+=("https://github.com/AlexanderP/tesseract-appimage/releases/download/v${v}/tesseract-${v}-x86_64.AppImage")
            done
            APPIMAGE="$TMP_TESS/tesseract.AppImage"
            if ! ERR="$(descargar "$APPIMAGE" 30000000 "${URLS[@]}")"; then
                fallar '4 de 7 - descargar el OCR' "no se pudo descargar el OCR: $ERR" "$REGISTRO" \
                       'Vuelve a ejecutar el instalador: puede haber sido un corte pasajero.' \
                       'Si tu red bloquea github.com, descarga este fichero desde otro equipo:' \
                       "  ${URLS[0]}" \
                       'y dejalo dentro de la carpeta tools/ del proyecto. Luego repite.'
            fi
        fi

        chmod +x "$APPIMAGE" 2>/dev/null || true
        detalle 'Extrayendo el OCR...'
        # --appimage-extract descomprime sin necesitar FUSE, que es justo lo
        # que no hay dentro de un contenedor ni en WSL sin configurar.
        if ! ( cd "$TMP_TESS" && "$APPIMAGE" --appimage-extract >/dev/null 2>&1 ); then
            fallar '4 de 7 - extraer el OCR' 'el AppImage del OCR no se dejo extraer' "$REGISTRO" \
                   'Vuelve a ejecutar el instalador; el fichero puede haberse descargado a medias.'
        fi
        SR="$TMP_TESS/squashfs-root"
        BIN_TESS="$(find "$SR" -type f -name tesseract -perm -u+x 2>/dev/null | head -1)"
        if [ -z "$BIN_TESS" ]; then
            fallar '4 de 7 - extraer el OCR' 'no encuentro tesseract en lo extraido' "$REGISTRO" \
                   'Vuelve a ejecutar el instalador.'
        fi

        rm -rf "$TESS_DIR"
        mkdir -p "$TESS_DIR/lib" "$TESS_DIR/tessdata"
        cp "$BIN_TESS" "$TESS_DIR/"
        CARGADOR="$(find "$SR" -maxdepth 2 -name 'ld-linux-x86-64.so.2' 2>/dev/null | head -1)"
        [ -n "$CARGADOR" ] && cp "$CARGADOR" "$TESS_DIR/"
        [ -d "$SR/usr/lib" ] && cp -a "$SR/usr/lib/." "$TESS_DIR/lib/"

        # Tesseract es Apache-2.0 y su AppImage arrastra librerias GPL y LGPL:
        # los avisos tienen que llegar al usuario, no quedarse en el squashfs
        # que se borra unas lineas mas abajo.
        mkdir -p "$TESS_DIR/licencias"
        find "$SR" -type f \( -iname 'LICEN[SC]E*' -o -iname 'COPYING*'              -o -iname 'NOTICE*' -o -iname 'AUTHORS*' \)              -exec cp -n {} "$TESS_DIR/licencias/" \; 2>/dev/null || true
        rmdir "$TESS_DIR/licencias" 2>/dev/null || true

        ORIGEN_TESSDATA="$(find "$SR" -type d -name tessdata 2>/dev/null | head -1)"
        if [ -n "$ORIGEN_TESSDATA" ]; then
            for l in "${IDIOMAS[@]}"; do
                [ -f "$ORIGEN_TESSDATA/$l.traineddata" ] && \
                    cp "$ORIGEN_TESSDATA/$l.traineddata" "$TESS_DIR/tessdata/"
            done
        fi

        # El AppImage trae su propia libc: hay que arrancarlo con su cargador,
        # o en una distribucion distinta a la que lo empaqueto no arranca.
        if [ -f "$TESS_DIR/ld-linux-x86-64.so.2" ]; then
            escribir_texto "$TESS_SH" \
                '#!/bin/sh' \
                'D="$(cd "$(dirname "$0")" && pwd)"' \
                'export TESSDATA_PREFIX="$D/tessdata"' \
                'exec "$D/ld-linux-x86-64.so.2" --library-path "$D/lib" "$D/tesseract" "$@"'
        else
            escribir_texto "$TESS_SH" \
                '#!/bin/sh' \
                'D="$(cd "$(dirname "$0")" && pwd)"' \
                'export TESSDATA_PREFIX="$D/tessdata"' \
                'export LD_LIBRARY_PATH="$D/lib:${LD_LIBRARY_PATH:-}"' \
                'exec "$D/tesseract" "$@"'
        fi
        chmod +x "$TESS_SH" "$TESS_DIR/tesseract"
        rm -rf "$TMP_TESS"
        trap - EXIT
    fi

    # Los idiomas que no trae el AppImage se completan del repositorio oficial.
    PENDIENTES="$(faltan_idiomas)"
    if [ -n "$PENDIENTES" ]; then
        mkdir -p "$TESS_DIR/tessdata"
        for l in $PENDIENTES; do
            detalle "Descargando el idioma $l..."
            if ! ERR="$(descargar "$TESS_DIR/tessdata/$l.traineddata" 1000000 \
                        "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata")"; then
                fallar '4 de 7 - descargar idiomas del OCR' "falta el idioma $l" "$REGISTRO" \
                       'Sin el idioma espanol los PDF escaneados en castellano saldran mal.' \
                       'Comprueba la conexion y vuelve a ejecutar el instalador.'
            fi
        done
    fi

    # Comprobacion de verdad: que el binario arranque en ESTA maquina.
    if ! "$TESS_SH" --list-langs >/dev/null 2>>"$REGISTRO"; then
        fallar '4 de 7 - comprobar el OCR' 'el OCR no arranca en este equipo' "$REGISTRO" \
               'Puede faltar alguna libreria del sistema. Revisa el registro.'
    fi
    bien "OCR listo con los idiomas: ${IDIOMAS[*]}"
fi

if [ "$SOLO_OCR" = 1 ]; then
    echo ""
    echo "  ${C_VERDE}Descarga del OCR terminada (--solo-ocr).${C_FIN}"
    pausar
    exit 0
fi

# -------------------------------------------------------------- 5. compilar

paso '[5 de 7] Compilando PDFx (tarda unos 5 minutos)'

rm -rf "$TRABAJO_PY" "$PORTABLE"
LOG_BUILD="$CARPETA_LOGS/log-pyinstaller-linux.txt"
rm -f "$LOG_BUILD"

if ! ejecutar "$LOG_BUILD" "$PY_VENV" -m PyInstaller "$RAIZ/build/pdfx.spec" --noconfirm \
        --distpath "$DIST_PLATAFORMA" --workpath "$TRABAJO_PY" \
    || [ ! -x "$PORTABLE/PDFx" ]; then
    fallar '5 de 7 - compilar' 'PyInstaller no genero el ejecutable PDFx' "$LOG_BUILD" \
           'Revisa el log de PyInstaller.' \
           'Si falta alguna libreria del sistema, saldra indicado ahi.'
fi
bien 'PDFx compilado'

# ----------------------------------------------------- 6. preparar la carpeta

paso '[6 de 7] Preparando la carpeta para la memoria USB'

if [ -x "$TESS_SH" ]; then
    mkdir -p "$PORTABLE/tools"
    cp -a "$TESS_DIR" "$PORTABLE/tools/"
    bien 'OCR copiado dentro de la carpeta'
else
    aviso 'La carpeta va SIN OCR: los PDF escaneados saldran vacios.'
fi

escribir_texto "$PORTABLE/EJECUTAR.sh" \
    '#!/bin/sh' \
    '# Abre la ventana de PDFx. Tambien acepta ordenes: ./EJECUTAR.sh convertir fichero.pdf' \
    'cd "$(dirname "$0")" && exec ./PDFx "$@"'
chmod +x "$PORTABLE/EJECUTAR.sh"

escribir_texto "$PORTABLE/CONVERTIR.sh" \
    '#!/bin/sh' \
    '# Convierte a Markdown los PDF que le pases:  ./CONVERTIR.sh informe.pdf otro.pdf' \
    'cd "$(dirname "$0")" || exit 1' \
    'if [ $# -eq 0 ]; then' \
    '  echo "Uso: ./CONVERTIR.sh fichero.pdf [mas ficheros...]"' \
    '  exit 1' \
    'fi' \
    'echo "Convirtiendo. No cierres esta ventana..."' \
    'echo' \
    './PDFx convertir "$@" --rapido' \
    'estado=$?' \
    'echo' \
    'if [ $estado -ne 0 ]; then' \
    '  echo "ALGO HA FALLADO. El motivo esta mas arriba."' \
    'else' \
    '  echo "Hecho. Los .md estan junto a cada PDF."' \
    'fi' \
    'exit $estado'
chmod +x "$PORTABLE/CONVERTIR.sh"

escribir_texto "$PORTABLE/LEEME_PRIMERO.txt" \
    'PDFx - convertir PDF a Markdown, Word y Excel' \
    '=============================================' \
    '' \
    'No hay que instalar nada. Este programa funciona sin' \
    'internet: ningun documento sale de tu ordenador.' \
    '' \
    'COMO SE USA' \
    '-----------' \
    'Desde el gestor de archivos, doble clic en  EJECUTAR.sh' \
    'y se abre la ventana. Si te pregunta, elige "Ejecutar".' \
    '' \
    'Desde el terminal:' \
    '  ./EJECUTAR.sh' \
    '' \
    'La primera vez puede tardar hasta un minuto en abrirse,' \
    'sobre todo desde una memoria USB. Ten paciencia.' \
    '' \
    'Para convertir sin abrir la ventana:' \
    '  ./CONVERTIR.sh informe.pdf' \
    'y deja un fichero .md al lado de cada PDF.' \
    '' \
    'SI COPIAS ESTA CARPETA A OTRO SITIO' \
    '-----------------------------------' \
    'Copiala ENTERA. El programa solo no funciona: necesita las' \
    'carpetas _internal y tools que estan a su lado.' \
    '' \
    'SI NO TE DEJA EJECUTARLO' \
    '------------------------' \
    'Puede que la memoria USB este montada sin permiso de' \
    'ejecucion. Copia la carpeta PDFx al disco duro (por' \
    'ejemplo a tu carpeta personal) y abrela desde ahi. Si hace' \
    'falta, devuelvele el permiso con:' \
    '  chmod +x PDFx/PDFx PDFx/EJECUTAR.sh PDFx/CONVERTIR.sh' \
    '  chmod +x PDFx/tools/tesseract-linux/tesseract*' \
    '  chmod +x PDFx/tools/tesseract-linux/ld-linux-x86-64.so.2' \
    '' \
    'SI LOS PDF ESCANEADOS SALEN VACIOS' \
    '----------------------------------' \
    'Lo primero: en la ventana, en el recuadro  Lectura ,' \
    'cambia el desplegable  OCR  de  auto  a  always .' \
    '' \
    'En  auto  el programa mira si la pagina ya trae texto, y' \
    'a un escaneo le basta con tener cabecera o numero de' \
    'pagina para que la de por leida y no mire la imagen: te' \
    'devuelve la pagina casi vacia. Con  always  la lee entera.' \
    '' \
    'Regla facil: si al abrir el PDF no puedes seleccionar el' \
    'texto con el raton, es un escaneo. Pon  always .' \
    '' \
    'Si sale un error de permisos (Permission denied), lo que' \
    'le falta al OCR es el permiso de ejecucion: usa las dos' \
    'ultimas ordenes de la seccion anterior.' \
    '' \
    'Y si no es nada de eso, falta la carpeta  tools  o esta' \
    'incompleta. Vuelve a copiar la carpeta PDFx entera desde' \
    'el origen.' \
    '' \
    'LICENCIA' \
    '--------' \
    'PDFx es software libre.  Copyright (C) 2026 Robin Gregorio.' \
    'Se reparte bajo la Licencia Publica General de GNU version 3;' \
    'el texto completo esta en  LICENSE.txt , aqui al lado. Se' \
    'entrega SIN NINGUNA GARANTIA.' \
    '' \
    'Puedes copiarlo y repartirlo libremente. El codigo fuente' \
    'esta en:' \
    '  https://github.com/robindanilo2218/PDFx' \
    '' \
    'Esta carpeta lleva ademas componentes hechos por otras' \
    'personas, con sus propias licencias. Estan todas en' \
    'TERCEROS.txt , aqui al lado.'

# Lo que se reparte es esta carpeta, no el repositorio, asi que la licencia y
# los avisos de terceros tienen que ir dentro: la GPL obliga a lo primero y la
# Apache-2.0 de Tesseract a lo segundo.
if [ -f "$RAIZ/LICENSE" ]; then
    cp "$RAIZ/LICENSE" "$PORTABLE/LICENSE.txt"
else
    aviso 'no hay LICENSE en la raiz: la carpeta se entrega sin licencia'
fi
if [ -f "$RAIZ/TERCEROS.txt" ]; then
    cp "$RAIZ/TERCEROS.txt" "$PORTABLE/TERCEROS.txt"
else
    aviso 'no hay TERCEROS.txt en la raiz: faltan los avisos de terceros'
fi

bien 'Carpeta preparada'

# ------------------------------------------------------------ 7. autoprueba

paso '[7 de 7] Comprobando que lo compilado funciona'

FALLOS=()
EXE="$PORTABLE/PDFx"

[ -x "$EXE" ] || FALLOS+=('falta el ejecutable PDFx')
if [ -f "$EXE" ]; then
    TAM="$(stat -c '%s' "$EXE")"
    [ "$TAM" -lt 1000000 ] && FALLOS+=('el ejecutable PDFx tiene un tamano imposible')
fi
[ -f "$PORTABLE/_internal/base_library.zip" ] || FALLOS+=('falta _internal/base_library.zip')
# Repartir la carpeta sin estos dos ficheros es incumplir la GPL de PDFx y la
# Apache-2.0 de Tesseract. Es un fallo, no un aviso que se pierde en el log.
[ -f "$PORTABLE/LICENSE.txt" ] || FALLOS+=('falta LICENSE.txt: la carpeta no se puede repartir sin licencia')
[ -f "$PORTABLE/TERCEROS.txt" ] || FALLOS+=('falta TERCEROS.txt: faltan los avisos de los componentes de terceros')
# _tkinter no esta siempre en el mismo sitio: en Linux con Python 3.13
# PyInstaller lo mete en _internal/python3.13/lib-dynload/. Se busca en todo
# el arbol en vez de suponer una ruta, que es justo lo que fallaba antes.
if ! find "$PORTABLE/_internal" -name '_tkinter*.so' -print -quit 2>/dev/null | grep -q .; then
    FALLOS+=('falta _tkinter: la ventana no abriria')
fi
# Los datos de Tcl/Tk cambian de nombre segun la version (_tk_data, tk8.6...).
# Se prueba nombre a nombre: un solo `ls` con varios candidatos devuelve error
# si falta cualquiera de ellos, aunque el bueno si este.
TK_OK=0
for d in _tk_data tk8.6 tk8.7 tk; do
    [ -d "$PORTABLE/_internal/$d" ] && { TK_OK=1; break; }
done
[ "$TK_OK" = 1 ] || FALLOS+=('faltan los datos de Tk: la ventana no abriria')

if [ -x "$PORTABLE/tools/tesseract-linux/tesseract.sh" ]; then
    for l in "${IDIOMAS[@]}"; do
        [ -f "$PORTABLE/tools/tesseract-linux/tessdata/$l.traineddata" ] || \
            FALLOS+=("falta el idioma $l del OCR")
    done
elif [ "$SOLO_COMPILAR" != 1 ]; then
    FALLOS+=('falta tools/tesseract-linux dentro de la carpeta')
fi

if [ "${#FALLOS[@]}" -gt 0 ]; then
    fallar '7 de 7 - comprobar el resultado' "$(IFS='; '; echo "${FALLOS[*]}")" "$LOG_BUILD" \
           'Vuelve a ejecutar el instalador.'
fi
bien 'Estructura de la carpeta correcta'

# Prueba de verdad: convertir un PDF escaneado con el ejecutable ya compilado.
# Es la unica comprobacion que demuestra a la vez el arranque, el OCR, la ruta
# de Tesseract dentro de la carpeta y la escritura del Markdown.
if [ "$SIN_PRUEBA" != 1 ] && [ -f "$RAIZ/tests/data/escaneado.pdf" ]; then
    PRUEBA="$(mktemp -d)"
    cp "$RAIZ/tests/data/escaneado.pdf" "$PRUEBA/"
    detalle 'Convirtiendo un PDF escaneado de prueba (puede tardar un minuto)...'
    SALIDA="$PRUEBA/salida.txt"
    if ! ( cd "$PORTABLE" && ./PDFx convertir "$PRUEBA/escaneado.pdf" --rapido -q ) \
            >"$SALIDA" 2>&1 || [ ! -f "$PRUEBA/escaneado.md" ]; then
        cp "$SALIDA" "$CARPETA_LOGS/salida-prueba.txt" 2>/dev/null || true
        fallar '7 de 7 - prueba de conversion' 'el ejecutable no pudo convertir el PDF de prueba' \
               "$SALIDA" 'Vuelve a ejecutar el instalador.'
    fi
    if grep -qi 'mantenimiento preventivo' "$PRUEBA/escaneado.md"; then
        bien 'Prueba de conversion correcta: el OCR lee un PDF escaneado'
    else
        aviso 'La conversion funciono pero el OCR no leyo el texto esperado. Revisa los idiomas del OCR.'
    fi
    rm -rf "$PRUEBA"
elif [ "$SIN_PRUEBA" != 1 ]; then
    aviso 'No he podido hacer la prueba de conversion (falta tests/data/escaneado.pdf).'
fi

# ------------------------------------------------------------------- final

DESTINO="$PORTABLE"
NUM="$(find "$DESTINO" -type f | wc -l)"
TAM_MB="$(du -sm "$DESTINO" | cut -f1)"

echo ""
echo "  ${C_VERDE}========================================================${C_FIN}"
echo "  ${C_VERDE}   LISTO${C_FIN}"
echo "  ${C_VERDE}========================================================${C_FIN}"
echo ""
echo "     Carpeta preparada:"
echo "       $DESTINO"
echo "       $TAM_MB MB, $NUM ficheros"
echo ""
echo "     QUE HACER AHORA"
echo "     ---------------"
echo "     1. Conecta la memoria USB."
echo "     2. Copia la CARPETA ENTERA llamada  PDFx  a la memoria."
echo "        IMPORTANTE: no copies solo el ejecutable. Sin la carpeta"
echo "        _internal el programa no arranca. Copia la carpeta"
echo "        completa, tal cual, con todo lo que hay dentro."
echo "     3. En el otro ordenador, abre la carpeta PDFx de la"
echo "        memoria y ejecuta  EJECUTAR.sh"
echo ""
echo "     Para llevartela comprimida:"
echo "       cd dist/linux && zip -r ../PDFx-portable-linux.zip PDFx"
echo ""
echo "     Dentro de la carpeta tienes  LEEME_PRIMERO.txt  con estos"
echo "     mismos pasos, por si no te acuerdas."

if [ "${#AVISOS[@]}" -gt 0 ]; then
    echo ""
    echo "     ${C_AMAR}AVISOS:${C_FIN}"
    for a in "${AVISOS[@]}"; do echo "       ${C_AMAR}- $a${C_FIN}"; done
fi

echo ""
echo "     ${C_GRIS}Registro de esta instalacion: $REGISTRO${C_FIN}"
echo ""
pausar
exit 0
