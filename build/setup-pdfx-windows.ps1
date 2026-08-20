#Requires -Version 5.1
<#
    Prepara la carpeta portable de PDFX para Windows, de principio a fin.

    No hay que ejecutar ningun otro script: este se basta solo. Comprueba el
    equipo, instala Python si hace falta, crea el entorno, descarga el OCR
    Tesseract, compila el ejecutable, verifica que lo compilado funciona de
    verdad y deja dist\windows\PDFX lista para copiar a una memoria USB.

    Un novato no ejecuta esto directamente: hace doble clic en INSTALAR_PDFX.bat,
    que esta en la raiz del proyecto. Windows no ejecuta ficheros .ps1 con doble
    clic (los abre en el Bloc de notas), de ahi el lanzador.

    Para el desarrollador:
        powershell -NoProfile -ExecutionPolicy Bypass -File build\setup-pdfx-windows.ps1
        ... -SoloTesseract   descarga el OCR y para
        ... -SoloCompilar    salta la descarga del OCR
        ... -SinPrueba       no ejecuta la prueba de conversion final
        ... -Auto            sin preguntas ni pausas (para automatizar)

    Todo el fichero es ASCII puro y sin tildes a proposito: Windows PowerShell
    5.1 lee los .ps1 sin BOM como ANSI, y cualquier caracter no ASCII saldria
    como basura en la consola del usuario.
#>

param(
    [switch]$SoloTesseract,
    [switch]$SoloCompilar,
    [switch]$SinPrueba,
    [switch]$Auto
)

$ErrorActionPreference = 'Stop'
# Sin esto, en 5.1 la barra de progreso multiplica por diez el tiempo de descarga.
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# ---------------------------------------------------------------- utilidades

$script:raiz = $null
if ($PSScriptRoot) { $script:raiz = Split-Path -Parent $PSScriptRoot }
elseif ($MyInvocation.MyCommand.Path) { $script:raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
if (-not $script:raiz -or -not (Test-Path (Join-Path $script:raiz 'pdfx'))) {
    Write-Host ''
    Write-Host '  No encuentro la carpeta del proyecto.' -ForegroundColor Red
    Write-Host '  Ejecuta este script asi, desde la carpeta del proyecto:'
    Write-Host '    powershell -NoProfile -ExecutionPolicy Bypass -File build\setup-pdfx-windows.ps1'
    Write-Host ''
    exit 1
}
Set-Location $script:raiz

$script:carpetaLogs = Join-Path $script:raiz 'build'
$script:registro    = Join-Path $script:carpetaLogs 'registro-instalacion.txt'
$script:avisos      = New-Object System.Collections.ArrayList

function Escribir-Registro([string]$texto) {
    try { Add-Content -Path $script:registro -Value $texto -Encoding UTF8 -ErrorAction SilentlyContinue } catch { }
}

function Pausar {
    if ($Auto) { return }
    if ($Host.Name -ne 'ConsoleHost') { return }
    Write-Host ''
    try { Read-Host '  Pulsa Intro para cerrar' | Out-Null } catch { }
}

function Paso([string]$texto) {
    Write-Host ''
    Write-Host ("  $texto") -ForegroundColor Cyan
    Escribir-Registro "`n=== $texto ==="
}

function Bien([string]$texto) {
    Write-Host ("     [OK] $texto") -ForegroundColor Green
    Escribir-Registro "[OK] $texto"
}

function Aviso([string]$texto) {
    Write-Host ("     [!]  $texto") -ForegroundColor Yellow
    Escribir-Registro "[!] $texto"
    [void]$script:avisos.Add($texto)
}

function Detalle([string]$texto) {
    Write-Host ("          $texto") -ForegroundColor DarkGray
}

function Fallar([string]$paso, [string]$motivo, [string[]]$consejos, [string]$log) {
    Write-Host ''
    Write-Host '  --------------------------------------------------------' -ForegroundColor Red
    Write-Host '     HA FALLADO. PDFX no se ha podido preparar.' -ForegroundColor Red
    Write-Host '  --------------------------------------------------------' -ForegroundColor Red
    Write-Host ''
    Write-Host "     Paso que fallo : $paso"
    Write-Host "     Motivo         : $motivo"
    Escribir-Registro "FALLO en $paso : $motivo"
    if ($consejos) {
        Write-Host ''
        Write-Host '     Que puedes hacer:'
        foreach ($c in $consejos) { Write-Host "       - $c" }
    }
    if ($log -and (Test-Path $log)) {
        Write-Host ''
        Write-Host '     Ultimas lineas del detalle tecnico:'
        Get-Content $log -Tail 25 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
    }
    Write-Host ''
    Write-Host '     Si vuelve a fallar, envia este fichero a quien te dio el programa:'
    Write-Host "       $script:registro"
    Write-Host ''
    Pausar
    exit 1
}

# Ejecuta un programa externo mostrando TODA su salida y devolviendo su codigo.
# En Windows PowerShell 5.1, redirigir stderr de un proceso nativo con 2>&1
# mientras ErrorActionPreference vale Stop convierte la primera linea de stderr
# en un error terminante. PyInstaller y pip escriben por stderr de forma normal,
# asi que hay que bajar la preferencia justo alrededor de la llamada.
function Ejecutar([string]$exe, [string[]]$argumentos, [string]$log) {
    Escribir-Registro "> $exe $($argumentos -join ' ')"
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $escritor = $null
    try {
        # El registro NO se escribe con Tee-Object. En Windows PowerShell 5.1
        # ese comando no admite -Encoding y guarda siempre en UTF-16, asi que
        # cada caracter ASCII ocupaba dos bytes y la mitad del fichero eran
        # ceros: los registros que se le piden al usuario cuando algo falla
        # salian ilegibles. Con un StreamWriter se elige UTF-8 sin BOM.
        # OJO: .NET no comparte el directorio actual con PowerShell, asi que
        # una ruta relativa iria a parar a otro sitio. Se absolutiza antes.
        if ($log) {
            $rutaLog = $log
            if (-not [System.IO.Path]::IsPathRooted($rutaLog)) {
                $rutaLog = Join-Path (Get-Location).ProviderPath $rutaLog
            }
            $escritor = New-Object System.IO.StreamWriter($rutaLog, $true, (New-Object System.Text.UTF8Encoding($false)))
        }
        # winget y pip dibujan barras y ruedas de progreso que, sin terminal
        # interactiva, salen como cientos de lineas de basura. Se descartan las
        # que no llevan ninguna letra ni digito. Se quitan tambien los bytes
        # nulos por si algun programa escribe en UTF-16 al verse redirigido.
        $texto = { param($l) ("$l" -replace "`0", '') }
        $util = { param($t) $t.Trim() -ne '' -and $t -match '[A-Za-z0-9]' }
        & $exe @argumentos 2>&1 |
            ForEach-Object { & $texto $_ } |
            Where-Object { & $util $_ } |
            ForEach-Object {
                if ($escritor) { $escritor.WriteLine($_) }
                Detalle $_
            }
        return $LASTEXITCODE
    } finally {
        if ($escritor) { $escritor.Dispose() }
        $ErrorActionPreference = $anterior
    }
}

# Como Ejecutar, pero con tope de tiempo y sin capturar la salida. Se usa con
# instaladores: si uno se queda esperando una ventana que nadie llega a ver
# -el caso tipico es el aviso de permisos de administrador en un equipo donde
# no se pueden conceder- colgaria la instalacion entera para siempre. Devuelve
# $true si el programa termino solo y $false si hubo que cerrarlo.
function Ejecutar-Con-Limite([string]$exe, [string[]]$argumentos, [int]$segundos) {
    Escribir-Registro "> $exe $($argumentos -join ' ')  (tope $segundos s)"
    $p = Start-Process -FilePath $exe -ArgumentList $argumentos -PassThru -WindowStyle Hidden
    if ($p.WaitForExit($segundos * 1000)) {
        $codigo = $null
        try { $codigo = $p.ExitCode } catch { }
        Escribir-Registro "  termino con el codigo $codigo"
        return $true
    }
    Escribir-Registro "  se paso de $segundos s: lo cierro"
    try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
    return $false
}

# Descarga con varios metodos en cascada.
#
# Invoke-WebRequest a secas NO vale para ficheros grandes en Windows PowerShell
# 5.1: carga la respuesta entera en memoria en vez de escribirla a disco segun
# llega, y con los 60 MB de Tesseract la conexion se corta ("La conexion ha
# terminado de forma inesperada"). Por eso se intenta primero con curl.exe, que
# viene de serie en Windows 10 1803 y posteriores, y va escribiendo a disco.
#
# Se prueban todas las fuentes y, si ninguna responde, se espera un poco y se
# repite la vuelta entera. Un corte de red de unos segundos -github cerrando la
# conexion de golpe, por ejemplo- no deberia echar por tierra una instalacion
# de quince minutos, y es un caso que pasa de verdad.
function Descargar([string[]]$urls, [string]$destino, [int]$minimoBytes) {
    $motivos = @()
    $rondas = 2
    for ($ronda = 1; $ronda -le $rondas; $ronda++) {
        foreach ($url in $urls) {
            $err = Descargar-Una $url $destino $minimoBytes
            if (-not $err) { return $null }
            $motivos += $err
        }
        if ($ronda -lt $rondas) {
            Detalle 'No ha entrado la descarga. Espero 15 segundos y lo intento otra vez...'
            Escribir-Registro '  ninguna fuente respondio: segunda ronda tras 15 s'
            Start-Sleep -Seconds 15
        }
    }
    return (($motivos | Select-Object -Unique) -join ' || ')
}

function Descargar-Una([string]$url, [string]$destino, [int]$minimoBytes) {
    Escribir-Registro "descargando $url"
    $motivos = @()

    function Bastante([string]$fichero) {
        if (-not (Test-Path $fichero)) { return $false }
        $n = (Get-Item $fichero).Length
        if ($n -eq 0) { return $false }
        if ($minimoBytes -gt 0 -and $n -lt $minimoBytes) { return $false }
        return $true
    }

    # 1) curl.exe: el mas fiable con ficheros grandes y redirecciones.
    $curl = $null
    if ($env:WINDIR) {
        $ruta = Join-Path $env:WINDIR 'System32\curl.exe'
        if (Test-Path $ruta) { $curl = $ruta }
    }
    if (-not $curl) {
        $c = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($c) { $curl = $c.Source }
    }
    if ($curl) {
        Remove-Item $destino -Force -ErrorAction SilentlyContinue
        Escribir-Registro '  metodo: curl.exe'
        $anterior = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $curl '-L' '--fail' '--silent' '--show-error' '--retry' '3' '--retry-delay' '2' `
                    '--connect-timeout' '30' '--max-time' '1800' `
                    '-o' $destino $url 2>&1 | ForEach-Object { Escribir-Registro "    $_" }
            $rc = $LASTEXITCODE
        } catch { $rc = -1 } finally { $ErrorActionPreference = $anterior }
        if ($rc -eq 0 -and (Bastante $destino)) { return $null }
        $motivos += "curl.exe fallo (codigo $rc)"
    }

    # 2) BITS: transferencia en segundo plano, reanudable. Puede estar apagada.
    if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
        Remove-Item $destino -Force -ErrorAction SilentlyContinue
        Escribir-Registro '  metodo: BITS'
        try {
            Start-BitsTransfer -Source $url -Destination $destino -ErrorAction Stop
            if (Bastante $destino) { return $null }
            $motivos += 'BITS dejo un fichero incompleto'
        } catch {
            $motivos += "BITS fallo ($($_.Exception.Message))"
        }
    }

    # 3) WebClient: escribe a disco segun llega, sin acumular en memoria.
    Remove-Item $destino -Force -ErrorAction SilentlyContinue
    Escribir-Registro '  metodo: WebClient'
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add('User-Agent', 'Mozilla/5.0 PDFX-setup')
        $wc.DownloadFile($url, $destino)
        $wc.Dispose()
        if (Bastante $destino) { return $null }
        $motivos += 'WebClient dejo un fichero incompleto'
    } catch {
        $motivos += "WebClient fallo ($($_.Exception.Message))"
    }

    # 4) Invoke-WebRequest como ultimo recurso.
    Remove-Item $destino -Force -ErrorAction SilentlyContinue
    Escribir-Registro '  metodo: Invoke-WebRequest'
    try {
        Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing -TimeoutSec 1800
        if (Bastante $destino) { return $null }
        $motivos += 'Invoke-WebRequest dejo un fichero incompleto'
    } catch {
        $motivos += "Invoke-WebRequest fallo ($($_.Exception.Message))"
    }

    Remove-Item $destino -Force -ErrorAction SilentlyContinue
    return "no se pudo descargar de $url. Intentos: $($motivos -join ' | ')"
}

function Texto-Windows([string[]]$lineas, [string]$ruta) {
    # El fin de linea se escribe CRLF a mano en vez de dejarselo a Set-Content:
    # el Bloc de notas y, sobre todo, los bloques if(...) de un .bat necesitan
    # CRLF, y no conviene que eso dependa de en que sistema se genere.
    # OJO: .NET no comparte el directorio actual con PowerShell, asi que una
    # ruta relativa iria a parar a otro sitio. Hay que absolutizarla antes.
    $absoluta = $ruta
    if (-not [System.IO.Path]::IsPathRooted($absoluta)) {
        $absoluta = Join-Path (Get-Location).ProviderPath $ruta
    }
    $texto = ($lineas -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText($absoluta, $texto, [System.Text.Encoding]::ASCII)
}

trap {
    Fallar 'inesperado' "$_" @('Vuelve a ejecutar INSTALAR_PDFX.bat. Lo que ya estaba hecho no se repite.') $script:registro
}

# ---------------------------------------------------------------- cabecera

if (-not (Test-Path $script:carpetaLogs)) { New-Item -ItemType Directory -Force -Path $script:carpetaLogs | Out-Null }
Set-Content -Path $script:registro -Value "PDFX - instalacion iniciada $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8

Write-Host ''
Write-Host '  ========================================================' -ForegroundColor Cyan
Write-Host '     PDFX - preparar la carpeta portable para el USB' -ForegroundColor Cyan
Write-Host '  ========================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host '     Esto tarda entre 10 y 25 minutos segun tu conexion.'
Write-Host '     Veras pasar muchas lineas de texto: es normal.'
Write-Host '     No cierres esta ventana hasta que ponga LISTO.'

# ---------------------------------------------------------------- 1. equipo

Paso '[1 de 7] Comprobando el equipo'

if ($script:raiz -match '\\AppData\\Local\\Temp\\') {
    Fallar '1 de 7 - comprobar el equipo' 'estas ejecutando desde dentro de un ZIP' @(
        'Extrae la carpeta primero: clic derecho sobre el ZIP -> Extraer todo.',
        'Luego abre la carpeta extraida y haz doble clic en INSTALAR_PDFX.bat.'
    ) ''
}

$unidad = (Get-Item $script:raiz).PSDrive
if ($unidad -and $unidad.Free) {
    $libresGB = [math]::Round($unidad.Free / 1GB, 1)
    if ($libresGB -lt 3) {
        Fallar '1 de 7 - comprobar el equipo' "solo hay $libresGB GB libres en $($unidad.Name): y hacen falta 3 GB" @(
            'Libera espacio en el disco y vuelve a ejecutar INSTALAR_PDFX.bat.'
        ) ''
    }
    Bien "Espacio libre: $libresGB GB"
}

if ($script:raiz.Length -gt 70) { Aviso 'La ruta del proyecto es larga. Si algo falla, copia el proyecto a C:\pdfx y repite.' }
if ($script:raiz -like '*OneDrive*') { Aviso 'El proyecto esta dentro de OneDrive. Si algo falla, copialo a C:\pdfx y repite.' }
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { Aviso 'Equipo ARM64: Tesseract correra emulado y el OCR ira mas lento.' }

try {
    Invoke-WebRequest -Uri 'https://pypi.org' -Method Head -TimeoutSec 15 -UseBasicParsing | Out-Null
    Bien 'Conexion a internet'
} catch {
    Aviso 'No he podido confirmar la conexion a internet. Si no hay red, los pasos 3 y 4 fallaran.'
}

# ---------------------------------------------------------------- 2. Python

Paso '[2 de 7] Buscando Python'

function Buscar-Python {
    foreach ($intento in @(
        @{ exe = 'py';     args = @('-3.12') },
        @{ exe = 'py';     args = @('-3')    },
        @{ exe = 'python'; args = @()        }
    )) {
        $cmd = Get-Command $intento.exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $anterior = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $version = & $intento.exe @($intento.args + '--version') 2>&1 | Out-String
        } catch { $version = '' } finally { $ErrorActionPreference = $anterior }
        if ($LASTEXITCODE -eq 0 -and $version -match 'Python 3\.(1[0-3])\b') {
            return @{ exe = $intento.exe; args = $intento.args; version = $version.Trim() }
        }
    }
    return $null
}

$python312 = Buscar-Python

if (-not $python312) {
    Write-Host '     [X]  Python no esta instalado' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '          PDFX necesita Python 3.12 para compilarse.'
    Write-Host '          Puedo instalarlo yo, solo para tu usuario, sin pedir'
    Write-Host '          permisos de administrador y sin tocar nada mas del equipo.'
    Write-Host ''
    $respuesta = 'S'
    if (-not $Auto) { $respuesta = Read-Host '          Instalar Python 3.12 ahora? (S/N)' }
    if ($respuesta -notmatch '^[SsYy]') {
        Fallar '2 de 7 - buscar Python' 'Python 3.12 no esta instalado' @(
            'Abre https://www.python.org/downloads/release/python-31210/',
            'Descarga "Windows installer (64-bit)".',
            'En la PRIMERA pantalla marca la casilla "Add python.exe to PATH".',
            'Pulsa "Install Now" y vuelve a ejecutar INSTALAR_PDFX.bat.'
        ) ''
    }

    Detalle 'Instalando Python 3.12 para tu usuario...'
    $instalado = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $rc = Ejecutar 'winget' @('install', '--id', 'Python.Python.3.12', '--exact', '--scope', 'user',
                                  '--accept-package-agreements', '--accept-source-agreements',
                                  '--disable-interactivity') $script:registro
        if ($rc -eq 0) { $instalado = $true }
    }
    if (-not $instalado) {
        $inst = Join-Path $env:TEMP 'python-3.12-instalador.exe'
        $err = Descargar 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $inst (20MB)
        if ($err) {
            Fallar '2 de 7 - instalar Python' $err @('Instala Python 3.12 a mano desde https://www.python.org/downloads/') ''
        }
        $p = Start-Process -FilePath $inst -Wait -PassThru -ArgumentList @(
            '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
            'Include_test=0', 'Include_doc=0', 'Shortcuts=0', 'AssociateFiles=0'
        )
        if ($p.ExitCode -ne 0) {
            Fallar '2 de 7 - instalar Python' "el instalador de Python termino con el codigo $($p.ExitCode)" @(
                'Instala Python 3.12 a mano desde https://www.python.org/downloads/ marcando "Add python.exe to PATH".'
            ) ''
        }
        Remove-Item $inst -Force -ErrorAction SilentlyContinue
    }

    # El PATH del proceso en curso no se refresca tras instalar: hay que ir a la
    # ruta absoluta conocida antes de volver a buscar.
    $rutaDirecta = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path $rutaDirecta) {
        $python312 = @{ exe = $rutaDirecta; args = @(); version = 'Python 3.12 (recien instalado)' }
    } else {
        $python312 = Buscar-Python
    }
    if (-not $python312) {
        Fallar '2 de 7 - instalar Python' 'Python se instalo pero no lo encuentro' @(
            'Cierra esta ventana, abre una nueva y vuelve a ejecutar INSTALAR_PDFX.bat.'
        ) ''
    }
}
Bien $python312.version

# ---------------------------------------------------------- 3. entorno y deps

Paso '[3 de 7] Instalando componentes (unos 150 MB, tarda unos 5 minutos)'

$pythonVenv = Join-Path $script:raiz '.venv\Scripts\python.exe'

# Un .venv creado en Linux tiene bin\ en vez de Scripts\. Como el proyecto se
# entrega copiando la carpeta, es muy facil que llegue uno inservible. Se
# comprueba el binario, nunca la carpeta.
if ((Test-Path '.venv') -and -not (Test-Path $pythonVenv)) {
    Aviso 'El .venv que hay es de otro sistema operativo y no sirve. Se rehace.'
    Remove-Item -Recurse -Force '.venv' -ErrorAction SilentlyContinue
    if (Test-Path '.venv') {
        Fallar '3 de 7 - preparar el entorno' 'no he podido borrar la carpeta .venv' @(
            'Borrala tu a mano y vuelve a ejecutar INSTALAR_PDFX.bat.'
        ) ''
    }
}

if (-not (Test-Path $pythonVenv)) {
    $rc = Ejecutar $python312.exe ($python312.args + @('-m', 'venv', '.venv')) $script:registro
    if ($rc -ne 0 -or -not (Test-Path $pythonVenv)) {
        Fallar '3 de 7 - preparar el entorno' 'no se pudo crear el entorno .venv' @(
            'Puede ser el antivirus. Desactivalo un momento y repite.',
            'O copia el proyecto a C:\pdfx y repite desde ahi.'
        ) $script:registro
    }
    Bien 'Entorno .venv creado'
} else {
    Bien 'Entorno .venv ya existente'
}

$logPip = Join-Path $script:carpetaLogs 'log-pip.txt'
Remove-Item $logPip -Force -ErrorAction SilentlyContinue

# Actualizar pip es deseable pero no imprescindible: si falla, se sigue.
Ejecutar $pythonVenv @('-m', 'pip', 'install', '--upgrade', 'pip') $logPip | Out-Null

$rc = Ejecutar $pythonVenv @('-m', 'pip', 'install', '-r', 'requirements-dev.txt') $logPip
if ($rc -ne 0) {
    Fallar '3 de 7 - instalar componentes' 'pip no pudo instalar las dependencias' @(
        'Comprueba que tienes internet.',
        'Si estas en una red de empresa con proxy, puede estar bloqueando pypi.org.'
    ) $logPip
}

$rc = Ejecutar $pythonVenv @('-m', 'PyInstaller', '--version') $logPip
if ($rc -ne 0) {
    Fallar '3 de 7 - instalar componentes' 'PyInstaller no quedo instalado' @('Revisa el log de pip.') $logPip
}
Bien 'Componentes instalados'

if ($SoloTesseract -and $SoloCompilar) { $SoloCompilar = $false }

# 7-Zip es la unica forma fiable de abrir el instalador de Tesseract, que por
# dentro es un paquete NSIS. La alternativa -lanzar el instalador con /S- exige
# permisos de administrador: sin ellos se queda esperando un aviso de permisos
# que nadie ve, no extrae nada y deja la carpeta vacia. Eso era justo lo que
# fallaba, y encima sin sintoma claro: el instalador devolvia codigo 0.
#
# Aqui se consigue un 7-Zip de usar y tirar SIN instalar nada y SIN pedir
# permisos: se descarga el .msi oficial y se abre con "msiexec /a", que es una
# copia administrativa (descomprime en una carpeta) y no una instalacion: no
# toca el registro, no crea desinstalador y no dispara ningun aviso. Por eso
# funciona tambien en los ordenadores de empresa que lo tienen todo bloqueado.
function Obtener-7Zip {
    # 1) El que ya haya en el equipo, incluida una copia previa nuestra.
    $candidatos = @(
        (Join-Path $script:raiz 'tools\7zip\7z.exe'),
        "$env:ProgramFiles\7-Zip\7z.exe",
        "${env:ProgramFiles(x86)}\7-Zip\7z.exe",
        "$env:LOCALAPPDATA\Programs\7-Zip\7z.exe"
    )
    foreach ($clave in @('HKLM:\SOFTWARE\7-Zip', 'HKCU:\SOFTWARE\7-Zip')) {
        try {
            $instalado = (Get-ItemProperty -Path $clave -Name Path -ErrorAction Stop).Path
            if ($instalado) { $candidatos += (Join-Path $instalado '7z.exe') }
        } catch { }
    }
    $enPath = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($enPath) { $candidatos += $enPath.Source }

    foreach ($ruta in $candidatos) {
        if ($ruta -and (Test-Path $ruta)) {
            Escribir-Registro "7-Zip encontrado en $ruta"
            return $ruta
        }
    }

    # 2) No hay ninguno: se trae una copia portable. Queda guardada en
    #    tools\7zip, asi que esto solo ocurre la primera vez.
    Detalle 'No hay 7-Zip en el equipo: consiguiendo una copia portable (2 MB)...'
    $sufijo = ''
    if ([Environment]::Is64BitOperatingSystem) { $sufijo = '-x64' }
    $urls = @()
    foreach ($v in @('2501', '2409', '2408', '2301')) {
        $urls += "https://www.7-zip.org/a/7z$v$sufijo.msi"
    }
    $msi = Join-Path $env:TEMP 'pdfx-7zip.msi'
    $err = Descargar $urls $msi (500KB)
    if ($err) {
        Escribir-Registro "no pude descargar 7-Zip: $err"
        return $null
    }

    $extraido = Join-Path $env:TEMP 'pdfx-7zip-msi'
    Remove-Item -Recurse -Force $extraido -ErrorAction SilentlyContinue
    $termino = Ejecutar-Con-Limite 'msiexec.exe' @('/a', "`"$msi`"", '/qn', "TARGETDIR=`"$extraido`"") 300
    Remove-Item -Force $msi -ErrorAction SilentlyContinue
    if (-not $termino) {
        Escribir-Registro 'msiexec se quedo colgado extrayendo 7-Zip'
        return $null
    }

    # Se busca el binario en vez de suponer donde cae: depende de la version.
    $origen = Get-ChildItem -Path $extraido -Filter '7z.exe' -Recurse -File -ErrorAction SilentlyContinue |
              Select-Object -First 1
    if (-not $origen) {
        Escribir-Registro 'el .msi de 7-Zip no contenia 7z.exe'
        Remove-Item -Recurse -Force $extraido -ErrorAction SilentlyContinue
        return $null
    }

    # 7z.exe no funciona solo: necesita 7z.dll al lado. Se copia la carpeta
    # entera y luego se quitan la ayuda y las traducciones, que sobran.
    $destino7z = Join-Path $script:raiz 'tools\7zip'
    Remove-Item -Recurse -Force $destino7z -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $destino7z | Out-Null
    Copy-Item -Path (Join-Path $origen.DirectoryName '*') -Destination $destino7z -Recurse -Force
    Remove-Item -Recurse -Force (Join-Path $destino7z 'Lang') -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $destino7z '7-zip.chm') -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $extraido -ErrorAction SilentlyContinue

    $final = Join-Path $destino7z '7z.exe'
    if (Test-Path $final) {
        Bien 'Copia portable de 7-Zip lista (no se ha instalado nada)'
        return $final
    }
    Escribir-Registro 'no consegui dejar 7z.exe en tools\7zip'
    return $null
}

# ------------------------------------------------------------- 4. Tesseract

$tessDir = Join-Path $script:raiz 'tools\tesseract'
$tessExe = Join-Path $tessDir 'tesseract.exe'
$idiomas = @('spa', 'eng', 'osd')

function Faltan-Idiomas {
    $faltan = @()
    foreach ($l in $idiomas) {
        if (-not (Test-Path (Join-Path $tessDir "tessdata\$l.traineddata"))) { $faltan += $l }
    }
    return $faltan
}

if ($SoloCompilar) {
    Paso '[4 de 7] Descarga del OCR omitida (-SoloCompilar)'
} else {
    Paso '[4 de 7] Descargando el OCR Tesseract (unos 60 MB, tarda unos 2 minutos)'

    # Se comprueba el binario y los idiomas, no la carpeta: una descarga cortada
    # deja la carpeta creada y vacia, y entonces no se reintentaria nunca.
    if ((Test-Path $tessExe) -and -not (Faltan-Idiomas)) {
        Bien 'El OCR ya estaba descargado y completo'
    } else {
        # OJO con la version: la 5.5.0.20241111 que se uso al principio NO existe,
        # ni como release de GitHub ni en el mirror; daba 404. Esta si, y pesa
        # 50.175.248 bytes en las dos fuentes.
        $version = '5.4.0.20240606'
        $nombreInst = "tesseract-ocr-w64-setup-$version.exe"
        $instalador = $null

        # Via de escape: si la red bloquea GitHub, el usuario puede bajarse el
        # instalador en otro equipo y dejarlo en tools\ o al lado del proyecto.
        foreach ($candidato in @(
            (Join-Path $script:raiz "tools\$nombreInst"),
            (Join-Path $script:raiz 'tools\tesseract-setup.exe'),
            (Join-Path $script:raiz $nombreInst),
            (Join-Path $script:raiz 'tesseract-setup.exe')
        )) {
            if ((Test-Path $candidato) -and (Get-Item $candidato).Length -gt 30MB) {
                $instalador = $candidato
                Bien "Usando el instalador que ya habias dejado en $candidato"
                break
            }
        }

        if (-not $instalador) {
            $urls = @(
                "https://github.com/UB-Mannheim/tesseract/releases/download/v$version/$nombreInst",
                "https://digi.bib.uni-mannheim.de/tesseract/$nombreInst"
            )
            $url = $urls[0]
            $instalador = Join-Path $env:TEMP 'tesseract-setup.exe'
            $err = Descargar $urls $instalador (30MB)
            if ($err) {
                Fallar '4 de 7 - descargar el OCR' $err @(
                    'Vuelve a ejecutar INSTALAR_PDFX.bat: puede haber sido un corte pasajero.',
                    'Si el antivirus corta la descarga, desactivalo un momento y repite.',
                    'Si tu red bloquea github.com, descarga este fichero desde otro equipo:',
                    "  $url",
                    'y dejalo dentro de la carpeta tools\ del proyecto. Luego repite.'
                ) $script:registro
            }
        }
        $borrarInstalador = ($instalador -like "$env:TEMP*")

        # Carpeta de paso SIN espacios: el instalador NSIS trata /D= de forma
        # especial y una ruta entrecomillada le sienta mal. Si el equipo no
        # deja crear carpetas en la raiz del disco, se cae a la temporal.
        $paso = Join-Path $env:SystemDrive 'pdfx-tess-tmp'
        try {
            Remove-Item -Recurse -Force $paso -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force -Path $paso -ErrorAction Stop | Out-Null
        } catch {
            $paso = Join-Path $env:TEMP 'pdfx-tess-tmp'
            Remove-Item -Recurse -Force $paso -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force -Path $paso | Out-Null
        }
        Escribir-Registro "carpeta de paso: $paso"

        # Con 7-Zip la extraccion es un descomprimido normal: ni permisos, ni
        # ventanas, ni nada que se pueda quedar colgado.
        $sevenZip = Obtener-7Zip
        $ocrExtraido = $false
        if ($sevenZip) {
            Detalle 'Extrayendo el OCR con 7-Zip...'
            $rc = Ejecutar $sevenZip @('x', $instalador, "-o$paso", '-y') $script:registro
            if ($rc -le 1) { $ocrExtraido = $true }   # 1 es solo aviso
            else { Escribir-Registro "7-Zip devolvio $rc" }
        }

        # Ultimo recurso: el propio instalador en modo silencioso. Solo sirve
        # con permisos de administrador, y por eso lleva tope de tiempo: sin
        # ellos se queda esperando un aviso invisible hasta el fin de los dias.
        if (-not $ocrExtraido) {
            Detalle 'Extrayendo con el propio instalador (puede pedir permisos)...'
            if (-not (Ejecutar-Con-Limite $instalador @('/S', "/D=$paso") 600)) {
                Aviso 'El instalador del OCR se quedo colgado y he tenido que cerrarlo.'
            }
        }

        # El instalador puede dejar el binario anidado. Se busca en vez de suponer.
        $encontrado = Get-ChildItem -Path $paso -Filter 'tesseract.exe' -Recurse -File -ErrorAction SilentlyContinue |
                      Select-Object -First 1
        if (-not $encontrado) {
            Fallar '4 de 7 - extraer el OCR' 'no encuentro tesseract.exe en lo extraido' @(
                'Hace falta 7-Zip para abrir el instalador del OCR y no he podido conseguirlo.',
                'Comprueba la conexion y vuelve a ejecutar INSTALAR_PDFX.bat.',
                'Si tu red bloquea www.7-zip.org, instala 7-Zip a mano desde',
                '  https://www.7-zip.org  y repite.',
                'Si no puedes instalar nada en este equipo, copia 7z.exe y 7z.dll',
                'de otro ordenador que tenga 7-Zip a esta carpeta y repite:',
                "  $(Join-Path $script:raiz 'tools\7zip')"
            ) $script:registro
        }

        Remove-Item -Recurse -Force $tessDir -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $tessDir | Out-Null
        Copy-Item -Path (Join-Path $encontrado.DirectoryName '*') -Destination $tessDir -Recurse -Force
        Remove-Item -Recurse -Force $paso -ErrorAction SilentlyContinue
        if ($borrarInstalador) { Remove-Item -Force $instalador -ErrorAction SilentlyContinue }
        # Tesseract es Apache-2.0 y arrastra DLL con licencia GPL y LGPL: sus
        # avisos tienen que llegar al usuario. Se rescatan AHORA porque la poda
        # de abajo se lleva doc\ y todos los *.html, que es justo donde estan.
        $licFuente = Get-ChildItem $tessDir -Recurse -File -ErrorAction SilentlyContinue |
                     Where-Object { $_.Name -match '(?i)^(licen[sc]e|copying|notice|authors|copyright)' }
        if ($licFuente) {
            $licTess = Join-Path $tessDir 'licencias'
            New-Item -ItemType Directory -Force -Path $licTess | Out-Null
            foreach ($f in $licFuente) {
                Copy-Item $f.FullName (Join-Path $licTess $f.Name) -Force -ErrorAction SilentlyContinue
            }
        }
        # Podar lo que PDFX no usa nunca. Solo se invoca tesseract.exe, asi que
        # las herramientas de entrenamiento (lstmtraining, text2image y demas)
        # son 64 MB muertos. Los DLL no se tocan: cuales necesita de verdad
        # tesseract.exe no se puede comprobar sin ejecutarlo en Windows, y
        # equivocarse ahi deja al cliente sin OCR.
        $inutiles = @(
            '$PLUGINSDIR', 'doc', 'tessdata\script',
            'tesseract-uninstall.exe', 'winpath.exe',
            'ambiguous_words.exe', 'classifier_tester.exe', 'cntraining.exe',
            'combine_lang_model.exe', 'combine_tessdata.exe', 'dawg2wordlist.exe',
            'lstmeval.exe', 'lstmtraining.exe', 'merge_unicharsets.exe',
            'mftraining.exe', 'set_unicharset_properties.exe',
            'shapeclustering.exe', 'text2image.exe', 'unicharset_extractor.exe',
            'wordlist2dawg.exe'
        )
        foreach ($sobra in $inutiles) {
            Remove-Item -Recurse -Force (Join-Path $tessDir $sobra) -ErrorAction SilentlyContinue
        }
        # Los manuales en HTML tampoco pintan nada en un portable, ni los .jar
        # del visor ScrollView, que solo se usa depurando y necesita Java.
        Get-ChildItem $tessDir -Filter '*.html' -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
        Get-ChildItem (Join-Path $tessDir 'tessdata') -Filter '*.jar' -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue

        if (-not (Test-Path $tessExe)) {
            Fallar '4 de 7 - extraer el OCR' 'tesseract.exe no quedo en tools\tesseract' @('Vuelve a ejecutar INSTALAR_PDFX.bat.') ''
        }
    }

    # Los idiomas extra del instalador se marcan como descarga aparte, asi que
    # puede que no vengan. Se completan uno a uno desde el repositorio oficial.
    $faltan = Faltan-Idiomas
    if ($faltan) {
        New-Item -ItemType Directory -Force -Path (Join-Path $tessDir 'tessdata') | Out-Null
        foreach ($l in $faltan) {
            Detalle "Descargando el idioma $l..."
            $err = Descargar "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata" `
                             (Join-Path $tessDir "tessdata\$l.traineddata") (1MB)
            if ($err) {
                Fallar '4 de 7 - descargar idiomas del OCR' "falta el idioma $l" @(
                    'Sin el idioma espanol los PDF escaneados en castellano saldran mal.',
                    'Comprueba la conexion y vuelve a ejecutar INSTALAR_PDFX.bat.'
                ) ''
            }
        }
    }
    # Podar los idiomas que no se usan: si no, son cientos de MB de mas.
    Get-ChildItem (Join-Path $tessDir 'tessdata') -Filter '*.traineddata' -ErrorAction SilentlyContinue |
        Where-Object { $idiomas -notcontains $_.BaseName } | Remove-Item -Force -ErrorAction SilentlyContinue

    # Tesseract necesita el runtime de Visual C++, que puede no estar en la
    # maquina de destino. Se lleva al lado del binario.
    $sys32 = if ($env:WINDIR) { Join-Path $env:WINDIR 'System32' } else { $null }
    foreach ($dll in @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')) {
        if (-not $sys32) { break }
        $origen = Join-Path $sys32 $dll
        $destino = Join-Path $tessDir $dll
        if ((Test-Path $origen) -and -not (Test-Path $destino)) {
            Copy-Item $origen $destino -Force -ErrorAction SilentlyContinue
        }
    }
    Bien "OCR listo con los idiomas: $($idiomas -join ', ')"
}

if ($SoloTesseract) {
    Write-Host ''
    Write-Host '  Descarga del OCR terminada (-SoloTesseract).' -ForegroundColor Green
    Pausar
    exit 0
}

# -------------------------------------------------------------- 5. compilar

Paso '[5 de 7] Compilando PDFX.exe (tarda unos 5 minutos)'

# Cada plataforma deja su portable en su propia carpeta. Si Windows y Linux
# escribieran los dos en dist\PDFX, compilar para una borraria el portable de
# la otra, y este proyecto esta hecho para construir las dos desde el mismo
# sitio. Lo que si se comparte es todo lo que importa: el codigo, el .spec,
# las pruebas y los requisitos.
$distPlataforma = 'dist\windows'
$portable       = 'dist\windows\PDFX'
$trabajoPy      = 'build\build-windows'

foreach ($sobra in @($trabajoPy, $portable)) {
    Remove-Item -Recurse -Force $sobra -ErrorAction SilentlyContinue
}
if (Test-Path "$portable\PDFX.exe") {
    Fallar '5 de 7 - compilar' 'no puedo borrar la compilacion anterior' @(
        'Tienes PDFX.exe abierto. Cierralo y vuelve a ejecutar INSTALAR_PDFX.bat.'
    ) ''
}

$logBuild = Join-Path $script:carpetaLogs 'log-pyinstaller.txt'
Remove-Item $logBuild -Force -ErrorAction SilentlyContinue
$rc = Ejecutar $pythonVenv @('-m', 'PyInstaller', 'build\pdfx.spec', '--noconfirm',
                             '--distpath', $distPlataforma, '--workpath', $trabajoPy) $logBuild
if ($rc -ne 0 -or -not (Test-Path "$portable\PDFX.exe")) {
    Fallar '5 de 7 - compilar' 'PyInstaller no genero PDFX.exe' @(
        'Suele ser el antivirus bloqueando la escritura. Desactivalo un momento y repite.',
        'Tambien puede ser una ruta demasiado larga: copia el proyecto a C:\pdfx y repite.'
    ) $logBuild
}
Bien 'PDFX.exe compilado'

# ----------------------------------------------------- 6. preparar la carpeta

Paso '[6 de 7] Preparando la carpeta para la memoria USB'

if (Test-Path $tessExe) {
    New-Item -ItemType Directory -Force -Path "$portable\tools" | Out-Null
    Copy-Item -Recurse -Force $tessDir "$portable\tools\"
    Bien 'OCR copiado dentro de la carpeta'
} else {
    Aviso 'La carpeta va SIN OCR: los PDF escaneados saldran vacios.'
}

Texto-Windows @(
    '@echo off',
    'rem Arrastra uno o varios PDF encima de este fichero.',
    'setlocal',
    'cd /d "%~dp0"',
    'if "%~1"=="" (',
    '  start "" "PDFX.exe"',
    '  exit /b',
    ')',
    'echo Convirtiendo. No cierres esta ventana...',
    'echo.',
    '"PDFX-consola.exe" %* --rapido',
    'echo.',
    'if errorlevel 1 (echo ALGO HA FALLADO. El motivo esta mas arriba.) else (echo Hecho. Los .md estan junto a cada PDF.)',
    'pause'
) "$portable\ARRASTRA_AQUI_TUS_PDF.bat"

Texto-Windows @(
    'PDFX - convertir PDF a Markdown, Word y Excel',
    '=============================================',
    '',
    'No hay que instalar nada. Este programa funciona sin',
    'internet: ningun documento sale de tu ordenador.',
    '',
    'COMO SE USA',
    '-----------',
    'Doble clic en  PDFX.exe  y se abre la ventana.',
    '',
    'La primera vez puede tardar hasta un minuto en abrirse,',
    'sobre todo desde una memoria USB. Ten paciencia.',
    '',
    'Tambien puedes arrastrar uno o varios PDF encima de',
    'ARRASTRA_AQUI_TUS_PDF.bat  y deja un fichero .md al lado',
    'de cada PDF.',
    '',
    'SI COPIAS ESTA CARPETA A OTRO SITIO',
    '-----------------------------------',
    'Copiala ENTERA. PDFX.exe solo no funciona: necesita las',
    'carpetas _internal y tools que estan a su lado.',
    '',
    'SI WINDOWS TE AVISA AL ABRIRLO',
    '------------------------------',
    'Puede salir una pantalla azul que dice',
    '"Windows protegio tu PC".',
    'Pulsa  "Mas informacion"  y luego  "Ejecutar de todas',
    'formas". Sale porque el programa no esta firmado',
    'digitalmente, no porque tenga nada malo.',
    '',
    'SI NO TE DEJA EJECUTARLO DESDE LA MEMORIA USB',
    '---------------------------------------------',
    'Algunos ordenadores de empresa bloquean los programas que',
    'estan en memorias USB. Copia la carpeta PDFX al disco duro',
    '(por ejemplo a tu carpeta Documentos) y abrela desde ahi.',
    '',
    'SI LOS PDF ESCANEADOS SALEN VACIOS',
    '----------------------------------',
    'Falta la carpeta  tools  o esta incompleta. Vuelve a',
    'copiar la carpeta PDFX entera desde el origen.',
    '',
    'LICENCIA',
    '--------',
    'PDFX es software libre.  Copyright (C) 2026 Robin Gregorio.',
    'Se reparte bajo la Licencia Publica General de GNU version 3;',
    'el texto completo esta en  LICENSE.txt , aqui al lado. Se',
    'entrega SIN NINGUNA GARANTIA.',
    '',
    'Puedes copiarlo y repartirlo libremente. El codigo fuente',
    'esta en:',
    '  https://github.com/robindanilo2218/PDFx',
    '',
    'Esta carpeta lleva ademas componentes hechos por otras',
    'personas, con sus propias licencias. Estan todas en',
    'TERCEROS.txt , aqui al lado.'
) "$portable\LEEME_PRIMERO.txt"

# Lo que se reparte es esta carpeta, no el repositorio, asi que la licencia y
# los avisos de terceros tienen que ir dentro: la GPL obliga a lo primero y la
# Apache-2.0 de Tesseract a lo segundo.
foreach ($par in @(@('LICENSE', 'LICENSE.txt'), @('TERCEROS.txt', 'TERCEROS.txt'))) {
    $origen = Join-Path $script:raiz $par[0]
    if (Test-Path $origen) {
        Copy-Item $origen (Join-Path $portable $par[1]) -Force
    } else {
        Aviso "no hay $($par[0]) en la raiz: la carpeta se entrega incompleta"
    }
}

Bien 'Carpeta preparada'

# ------------------------------------------------------------ 7. autoprueba

Paso '[7 de 7] Comprobando que lo compilado funciona'

$fallos = @()
$consolaExe = "$portable\PDFX-consola.exe"

if (-not (Test-Path "$portable\PDFX.exe")) { $fallos += 'falta PDFX.exe' }
elseif ((Get-Item "$portable\PDFX.exe").Length -lt 1MB) { $fallos += 'PDFX.exe tiene un tamano imposible' }
if (-not (Test-Path $consolaExe)) { $fallos += 'falta PDFX-consola.exe (el .spec no se actualizo)' }
if (-not (Test-Path "$portable\_internal\base_library.zip")) { $fallos += 'falta _internal\base_library.zip' }
# Repartir la carpeta sin estos dos ficheros es incumplir la GPL de PDFX y la
# Apache-2.0 de Tesseract. Es un fallo, no un aviso que se pierde en el log.
if (-not (Test-Path "$portable\LICENSE.txt")) { $fallos += 'falta LICENSE.txt: la carpeta no se puede repartir sin licencia' }
if (-not (Test-Path "$portable\TERCEROS.txt")) { $fallos += 'falta TERCEROS.txt: faltan los avisos de los componentes de terceros' }
# _tkinter no cae siempre en la raiz de _internal: en Linux con Python 3.13,
# PyInstaller lo mete en _internal/python3.13/lib-dynload/. En Windows hoy si
# esta en la raiz, pero se busca en el arbol para que un cambio de version no
# de por rota una compilacion que en realidad esta bien.
if (-not (Get-ChildItem "$portable\_internal" -Filter '_tkinter*.pyd' -Recurse -ErrorAction SilentlyContinue)) {
    $fallos += 'falta _tkinter: la ventana no abriria'
}
# Los datos de Tcl/Tk cambian de nombre segun la version: _tk_data, tk8.6...
$tkDatos = @('_tk_data', 'tk8.6', 'tk8.7', 'tk') |
           Where-Object { Test-Path (Join-Path "$portable\_internal" $_) }
if (-not $tkDatos) { $fallos += 'faltan los datos de Tk: la ventana no abriria' }

if (Test-Path "$portable\tools\tesseract\tesseract.exe") {
    foreach ($l in $idiomas) {
        if (-not (Test-Path "$portable\tools\tesseract\tessdata\$l.traineddata")) { $fallos += "falta el idioma $l del OCR" }
    }
    if (-not (Test-Path "$portable\tools\tesseract\msvcp140.dll")) {
        Aviso 'No he podido incluir msvcp140.dll; en un equipo sin Visual C++ el OCR podria no arrancar.'
    }
} else {
    $fallos += 'falta tools\tesseract\tesseract.exe dentro de la carpeta'
}

if ($fallos) {
    Fallar '7 de 7 - comprobar el resultado' ($fallos -join '; ') @(
        'Vuelve a ejecutar INSTALAR_PDFX.bat.'
    ) $logBuild
}
Bien 'Estructura de la carpeta correcta'

# Prueba de verdad: convertir un PDF escaneado con el ejecutable ya compilado.
# Es la unica comprobacion que demuestra a la vez el arranque, el OCR, la ruta
# de Tesseract dentro de la carpeta y la escritura del Markdown.
if (-not $SinPrueba -and (Test-Path 'tests\data\escaneado.pdf') -and (Test-Path $consolaExe)) {
    $pruebaDir = Join-Path $env:TEMP ('pdfx_prueba_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $pruebaDir | Out-Null
    Copy-Item 'tests\data\escaneado.pdf' $pruebaDir
    $pdfPrueba = Join-Path $pruebaDir 'escaneado.pdf'
    $salida = Join-Path $pruebaDir 'salida.txt'
    Detalle 'Convirtiendo un PDF escaneado de prueba (puede tardar un minuto)...'
    $p = Start-Process -FilePath (Resolve-Path $consolaExe) `
                       -ArgumentList @('convertir', "`"$pdfPrueba`"", '--rapido', '-q') `
                       -Wait -PassThru -NoNewWindow `
                       -RedirectStandardOutput $salida -RedirectStandardError "$salida.err"
    $md = Join-Path $pruebaDir 'escaneado.md'
    if ($p.ExitCode -ne 0 -or -not (Test-Path $md)) {
        Copy-Item "$salida.err" $script:carpetaLogs -Force -ErrorAction SilentlyContinue
        Fallar '7 de 7 - prueba de conversion' 'el ejecutable no pudo convertir el PDF de prueba' @(
            'Vuelve a ejecutar INSTALAR_PDFX.bat.'
        ) "$salida.err"
    }
    $texto = (Get-Content $md -Raw -Encoding UTF8).ToLower()
    if ($texto -notmatch 'mantenimiento preventivo') {
        Aviso 'La conversion funciono pero el OCR no leyo el texto esperado. Revisa los idiomas del OCR.'
    } else {
        Bien 'Prueba de conversion correcta: el OCR lee un PDF escaneado'
    }
    Remove-Item -Recurse -Force $pruebaDir -ErrorAction SilentlyContinue
} elseif (-not $SinPrueba) {
    Aviso 'No he podido hacer la prueba de conversion (falta tests\data\escaneado.pdf).'
}

# ------------------------------------------------------------------- final

$destino = (Resolve-Path $portable).Path
$ficheros = Get-ChildItem $destino -Recurse -File -Force
$tamMB = [math]::Round((($ficheros | Measure-Object Length -Sum).Sum) / 1MB)

Write-Host ''
Write-Host '  ========================================================' -ForegroundColor Green
Write-Host '     LISTO' -ForegroundColor Green
Write-Host '  ========================================================' -ForegroundColor Green
Write-Host ''
Write-Host '     Carpeta preparada:'
Write-Host "       $destino" -ForegroundColor White
Write-Host "       $tamMB MB, $($ficheros.Count) ficheros"
Write-Host ''
Write-Host '     QUE HACER AHORA'
Write-Host '     ---------------'
Write-Host '     1. Conecta la memoria USB.'
Write-Host '     2. Copia la CARPETA ENTERA llamada  PDFX  a la memoria.'
Write-Host '        IMPORTANTE: no copies solo PDFX.exe. Sin la carpeta'
Write-Host '        _internal el programa no arranca. Copia la carpeta'
Write-Host '        completa, tal cual, con todo lo que hay dentro.'
Write-Host '     3. En el otro ordenador, abre la carpeta PDFX de la'
Write-Host '        memoria y haz doble clic en  PDFX.exe'
Write-Host ''
Write-Host '     Dentro de la carpeta tienes  LEEME_PRIMERO.txt  con estos'
Write-Host '     mismos pasos, por si no te acuerdas.'

if ($script:avisos.Count -gt 0) {
    Write-Host ''
    Write-Host '     AVISOS:' -ForegroundColor Yellow
    foreach ($a in $script:avisos) { Write-Host "       - $a" -ForegroundColor Yellow }
}

# Ofrecer la copia al USB: es literalmente el paso siguiente del usuario.
if (-not $Auto) {
    $usb = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($usb) {
        $libres = [math]::Round($usb.FreeSpace / 1GB, 1)
        Write-Host ''
        Write-Host "     He visto una memoria USB conectada: $($usb.DeviceID)\  ($libres GB libres)"
        $r = Read-Host '     Quieres que copie la carpeta PDFX ahi ahora? (S/N)'
        if ($r -match '^[SsYy]') {
            $rutaUsb = Join-Path "$($usb.DeviceID)\" 'PDFX'
            Detalle "Copiando a $rutaUsb ..."
            $rc = Ejecutar 'robocopy' @($destino, $rutaUsb, '/E', '/R:1', '/W:1', '/NP', '/NJH', '/NJS') $script:registro
            if ($rc -lt 8) { Bien "Copiado a $rutaUsb" }
            else { Aviso "La copia al USB fallo (codigo $rc). Copiala tu con el Explorador." }
        }
    }
}

Write-Host ''
Write-Host "     Registro de esta instalacion: $script:registro" -ForegroundColor DarkGray
Write-Host ''

try { Start-Process explorer.exe "/select,`"$destino\PDFX.exe`"" -ErrorAction SilentlyContinue } catch { }
Pausar
exit 0
