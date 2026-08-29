# PDFx — conversor de PDF sin conexión

Convierte PDF (incluidos los **escaneados** y los que son sólo imagen) a
**Markdown, Word, Excel, HTML, texto plano y JSON**, extrayendo además las
imágenes y los esquemas. Todo ocurre en la máquina del usuario: **el programa
no hace ni una sola conexión de red**.

Pensado para un caso concreto: poder trabajar con documentación técnica
(manuales de maquinaria, informes de planta, albaranes) sin subir el PDF
original a ningún servicio, y con la posibilidad de **tachar antes lo que sea
confidencial**.

---

## Descargas

### Portables (recomendado — sin instalación)

Descárgalos desde Google Drive y ejecuta:

- **Windows:** doble clic en `PDFx.exe`
- **Linux:** `./EJECUTAR.sh`

📥 **[Carpeta con todos los portables](https://drive.google.com/drive/folders/19BXyMfmLa0foWsRnT95IyGu8oGBraKk4?usp=drive_link)**

O descarga uno por uno:

- [PDFx-portable-windows.zip](https://drive.google.com/file/d/1hBHnex3k_klmv7HeCjCeZE8crF5TEC-K/view?usp=drive_link) — 115 MB
- [PDFx-portable-linux.zip](https://drive.google.com/file/d/1KuFCfaPGVfyUv0QIlPX1O5xoWyIAbI7o/view?usp=drive_link) — 99 MB
- [Código fuente (PDFx-proyecto.zip)](https://drive.google.com/file/d/12OANRy1Cjw5SNR9ZE_1eVHMjr2Ox9PzJ/view?usp=drive_link) — 0,9 MB

### ¿Sólo quieres usarlo?

👉 **[Guía rápida](docs/GUIA-RAPIDA.md)** — cómo abrirlo, el único ajuste que de
verdad importa (y por qué los escaneados salen vacíos si no lo tocas), cómo
tachar lo confidencial y qué hacer cuando algo falla. Sin jerga.

---

## Qué resuelve

| Problema | Cómo lo resuelve PDFx |
|---|---|
| MarkItDown y similares no leen PDF escaneados | OCR integrado (Tesseract 5) con enderezado y realce de contraste |
| Las tablas escaneadas salen destrozadas | Detección del rayado sobre la imagen + segunda lectura celda a celda |
| Los esquemas y fotos se pierden | Se recortan las zonas gráficas que el OCR no reconoció como texto |
| Enviar un PDF a un asistente consume muchos tokens | El `.md` ocupa entre 3 y 5 veces menos que el PDF paginado como imagen |
| No se quiere compartir información sensible | Saneado con revisión previa, pseudónimos estables e informe de verificación |
| No se puede instalar software en el equipo | Carpeta portable: se copia, se ejecuta, no toca el registro ni requiere permisos |

---

## Instalación

### Para el usuario final (portable)

No hay instalación. Se copia la carpeta `PDFx` (a un USB, al escritorio, a una
unidad de red) y se ejecuta:

- **Windows:** doble clic en `PDFx.exe`
- **Linux:** `./EJECUTAR.sh`

Al abrirlo sin argumentos aparece la ventana. En Windows también se puede
**arrastrar uno o varios PDF sobre `ARRASTRA_AQUI_TUS_PDF.bat`** para
convertirlos a `.md` al instante.

### Generar el portable de Windows

Un solo paso. En la carpeta del proyecto, **doble clic en `INSTALAR_PDFx.bat`**.

Se encarga de todo: comprueba el equipo, instala Python 3.12 si no está (sólo
para tu usuario, sin permisos de administrador), crea el entorno, descarga el
OCR Tesseract con los idiomas español e inglés, compila el ejecutable,
**verifica convirtiendo un PDF escaneado de prueba** y deja `dist\windows\PDFx` lista.
Al terminar ofrece copiarla a la memoria USB que tengas conectada.

Tarda entre 10 y 25 minutos y necesita internet **una sola vez**, en la máquina
que compila. El portable que sale ya no vuelve a necesitar red nunca.

No hay que instalar nada antes. Para abrir el instalador del OCR hace falta
7-Zip; si el equipo no lo tiene, el script se descarga una copia portable y la
usa **sin instalarla**, así que tampoco hacen falta permisos de administrador.

> El `.bat` existe porque Windows no ejecuta ficheros `.ps1` con doble clic: los
> abre en el Bloc de notas. El `.bat` sólo lanza el PowerShell, no tiene lógica.

Para el desarrollador, el mismo script acepta parámetros:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build\setup-pdfx-windows.ps1
#   -SoloTesseract   descarga el OCR y para
#   -SoloCompilar    salta la descarga del OCR
#   -SinPrueba       no ejecuta la prueba de conversión final
#   -Auto            sin preguntas ni pausas
```

Si algo falla, el motivo sale en pantalla y el detalle completo queda en
`build\registro-instalacion.txt`.

### Un solo proyecto, un portable por plataforma

Windows y Linux se construyen desde esta misma carpeta y **no se pisan**. Lo que
importa es común —el código de `pdfx/`, el `.spec`, las pruebas y los
requisitos—; sólo se separa lo que genera cada compilación:

| | Windows | Linux |
|---|---|---|
| Entrada | `INSTALAR_PDFx.bat` | `INSTALAR_PDFx.sh` |
| Portable | `dist/windows/PDFx` | `dist/linux/PDFx` |
| Entorno | `.venv` | `.venv-linux` |
| Trabajo de PyInstaller | `build/build-windows` | `build/build-linux` |
| OCR | `tools/tesseract` | `tools/tesseract-linux` |
| Registro | `build/registro-instalacion.txt` | `build/registro-instalacion-linux.txt` |

En los dos casos la carpeta que se entrega se llama `PDFx`, así que el usuario
final ve exactamente lo mismo en cualquiera de los dos sistemas.

### Generar el portable de Linux

Un solo paso, igual que en Windows:

```bash
./INSTALAR_PDFx.sh          # o bien:  bash INSTALAR_PDFx.sh
```

Hace lo mismo que su gemelo de Windows: comprueba el equipo, instala las piezas
del sistema que falten (`python3-venv`, `python3-tk`, `binutils` — pedirá tu
contraseña si hace falta), crea el entorno, descarga el OCR Tesseract con los
idiomas español e inglés, compila, **verifica convirtiendo un PDF escaneado de
prueba** y deja `dist/linux/PDFx` lista.

Para el desarrollador, los mismos parámetros:

```bash
./INSTALAR_PDFx.sh
#   --solo-ocr        descarga el OCR y para
#   --solo-compilar   salta la descarga del OCR
#   --sin-prueba      no ejecuta la prueba de conversión final
#   --auto            sin preguntas ni pausas
```

`build/obtener_tesseract.sh` y `build/construir_linux.sh` siguen existiendo,
pero ahora sólo delegan en el instalador: la lógica vive en un único sitio.

Para llevártela comprimida:

```bash
cd dist/linux && rm -f ../PDFx-portable-linux.zip && zip -r ../PDFx-portable-linux.zip PDFx
```

---

## La ventana

**1. Convertir** — se añaden los PDF, se marcan los formatos de salida, se
elige dónde guardar y se pulsa *Convertir*. El botón
**«Modo rápido: PDF → .md al lado del original»** hace lo mínimo imprescindible:
deja un `.md` con el mismo nombre junto al PDF, sin carpetas ni imágenes.

**2. Revisar y ocultar** — analiza el documento y propone lo que parece
confidencial (empresas, nombres, correos, teléfonos, códigos de máquina, IBAN,
identificadores fiscales, encabezados repetidos), con su recuento, las páginas
donde aparece y el contexto. Se marca lo que debe desaparecer, se añaden
términos propios y se aplica. La lista se puede guardar y reutilizar en otros
documentos.

**3. Ver Markdown** — visor con formato real (títulos, negritas, listas,
tablas, código e imágenes en línea), tema claro u oscuro y zoom. Abre cualquier
`.md`, no sólo lo que genera el programa.

---

## Línea de comandos

```bash
pdfx informe.pdf                          # -> informe.md
pdfx informe.pdf -f md,docx,xlsx -o salida/
pdfx *.pdf --rapido                       # lote a .md
pdfx plano.pdf --ocr always --dpi 400     # forzar OCR a más resolución
pdfx manual.pdf --paginas 1-12,40-

pdfx revisar contrato.pdf -o revision.json    # ver qué es sensible
pdfx contrato.pdf --ocultar-fichero revision.json

pdfx info                                  # estado del OCR y de la ventana
pdfx interfaz                              # abrir la ventana
```

Saneado directo desde la línea de comandos:

```bash
pdfx informe.pdf \
    --ocultar "Talleres Munoz S.L." --ocultar "Javier Ortega" \
    --ocultar-detector email,phone,serial \
    --ocultar-estilo label
```

Estilos de sustitución:

| Estilo | Resultado | Cuándo usarlo |
|---|---|---|
| `label` | `[CONFIDENCIAL_1]` | Por defecto. Cada entidad mantiene una etiqueta propia, así el documento sigue siendo comprensible |
| `mask` | `[OCULTO]` | Cuando ni siquiera interesa distinguir entre términos |
| `hash` | `[REF:9F2A1C]` | Trazabilidad interna sin revelar el original |
| `remove` | *(se borra)* | Máxima discreción |

El pseudónimo es **estable**: `MUÑOZ MAQUINARIA`, `Munoz Maquinaria` y
`Muñoz  Maquinaria` reciben los tres la misma etiqueta.

---

## Cómo decide qué hacer con cada página

```
página
  ├── ¿tiene capa de texto aprovechable?
  │      sí → pdfplumber: palabras, fuentes y tamaños
  │           tablas con pdfplumber (rayado y alineación)
  │      no → render a 300 ppp → contraste → enderezado
  │           Tesseract (TSV: palabra + caja + confianza)
  │           tablas por rayado detectado en la imagen
  │             └── celdas vacías → se releen recortadas una a una
  │           figuras: zonas con tinta que no son texto → recorte
  ├── columnas (sobre las palabras, antes de agrupar renglones)
  ├── renglones → párrafos, títulos y listas
  └── orden de lectura: columna a columna, de arriba abajo
```

Detalles que marcan la diferencia en documentos reales:

- **Enderezado único.** El OCR, el rayado de tablas y el recorte de figuras
  trabajan sobre exactamente los mismos píxeles; si no, la rejilla detectada no
  coincide con las palabras.
- **Segunda pasada por celda.** Tesseract en modo página se salta las cabeceras
  con fondo de color y las celdas con un número suelto. Las celdas vacías se
  releen recortadas y ampliadas.
- **Viñetas.** En PDF nativos la viñeta suele venir en una fuente de símbolos y
  se extrae como una letra suelta; en OCR aparece como `o` o `O`. Se detectan
  por la fuente y por la alineación vertical de la marca.
- **Nada de tablas fantasma.** Se rechaza una rejilla si parte palabras por la
  mitad, si sus celdas contienen prosa larga o si el OCR de página apenas
  encontró texto dentro (eso es un plano, no una tabla).
- **Columnas antes que renglones.** Agrupar renglones primero fusiona las dos
  columnas en una misma línea y el texto sale entrelazado.

---

## Salidas

| Formato | Contenido |
|---|---|
| `.md` | Títulos, párrafos, listas, tablas GFM, imágenes enlazadas, marcas de página y cabecera de metadatos |
| `.docx` | Estilos reales de Word (`Heading N`, `List Bullet`), tablas con rejilla, imágenes incrustadas |
| `.xlsx` | Una hoja por tabla más una hoja índice con enlaces; los números en formato español (`1.240,50`) se convierten a número real |
| `.html` | Un solo fichero con las imágenes incrustadas en base64; tema claro/oscuro y hoja de impresión |
| `.txt` | Texto plano, tablas separadas por tabuladores |
| `.json` | Modelo completo con cajas, confianza del OCR y origen de cada tabla, para automatizar |

Las imágenes van a una subcarpeta `media/` (o `<nombre>_media/` en modo rápido).

---

## Sobre el uso con asistentes de IA

El `.md` empieza con una cabecera que deja claro que el contenido **ya está
extraído**, de modo que el asistente trabaja sobre el texto en lugar de pedir
el PDF. Se puede desactivar con la casilla *Cabecera para asistentes de IA*.

Coste aproximado de un informe de 2 páginas con tabla e imagen:

| Qué se envía | Tokens aprox. |
|---|---|
| El PDF original (se procesa como imagen, página a página) | 3.000 – 6.000 |
| El `.md` generado | ~520 |

Y si además se activa el saneado, lo que sale de la empresa ya va sin nombres,
teléfonos, correos ni referencias de máquina.

---

## Idiomas del OCR

Vienen `spa`, `eng` y `osd`. Para añadir más, se copian los ficheros
`.traineddata` en `tools/tesseract/tessdata` (Windows) o
`tools/tesseract-linux/tessdata` (Linux) y se indican separados por `+`:

```bash
pdfx documento.pdf --idioma spa+eng+deu
```

Si se pide un idioma que no está instalado, el programa avisa y sigue con los
que sí tiene, en lugar de fallar.

---

## Licencia

PDFx es software libre, bajo la **Licencia Pública General de GNU, versión 3**.
El texto completo está en [LICENSE](LICENSE).

```
Copyright (C) 2026 Robin Gregorio

Este programa es software libre: puedes redistribuirlo y modificarlo bajo los
términos de la Licencia Pública General de GNU, versión 3, tal como la publica
la Free Software Foundation.

Se distribuye con la esperanza de que sea útil, pero SIN NINGUNA GARANTÍA; ni
siquiera la garantía implícita de COMERCIALIZACIÓN o de IDONEIDAD PARA UN FIN
DETERMINADO. Consulta la Licencia Pública General de GNU para más detalles.
```

En la práctica, para quien recibe PDFx: puede usarlo para lo que quiera,
copiarlo y repartirlo. Si lo modifica y reparte su versión, tiene que
publicarla también bajo la GPL v3 y dar acceso al código.

**Código fuente:** <https://github.com/robindanilo2218/PDFx>

Esa dirección es también la respuesta a lo que la GPL exige de quien reparte el
portable: entregar el código correspondiente, o decir dónde está. Aparece dentro
de la carpeta, en `LEEME_PRIMERO.txt`.

### Lo que va dentro del ejecutable

Ninguna de estas licencias entra en conflicto con la GPL v3:

| Componente | Licencia |
|---|---|
| pypdfium2 / PDFium | Apache-2.0 / BSD-3 |
| pdfplumber, pdfminer.six | MIT |
| python-docx, openpyxl | MIT |
| Pillow | MIT-CMU |
| numpy | BSD-3 |
| CPython, Tcl/Tk | PSF-2.0, BSD |
| Tesseract OCR | Apache-2.0 |
| PyInstaller | GPL **con excepción**; sólo construye, no se reparte |

Se ha descartado PyMuPDF a propósito: es AGPL-3.0, y la AGPL alcanza también al
uso a través de la red, que es más de lo que este proyecto quiere asumir.

### Lo que acompaña al OCR

Tesseract arrastra unas cincuenta bibliotecas del sistema, y **algunas son GPL o
LGPL**: `libstdc++`, `libgcc`, `libjbig`, `libiconv`, `glibc`, `libnettle` y
compañía. Son programas separados —viajan al lado del ejecutable, no dentro—,
pero sus avisos tienen que acompañar a la carpeta.

La lista completa, con el texto íntegro de la licencia Apache 2.0 y con dónde
conseguir el código de cada una, está en [TERCEROS.txt](TERCEROS.txt). Ese
fichero se copia dentro del portable en cada compilación, y el paso 7 del
instalador **falla** si no está.

---

## Estructura del proyecto

```
pdfx/
  cli.py              línea de comandos
  gui.py              ventana (Tkinter)
  mdview.py           visor de Markdown
  convert.py          orquestador: modelo -> saneado -> ficheros
  pipeline.py         PDF -> modelo de documento
  model.py            Word / Line / Block / Table / ImageRef / Page / Document
  config.py           ajustes
  redact.py           saneado y pseudónimos
  scan_sensitive.py   propuesta de términos a revisar
  engines/            render, texto nativo, imágenes, OCR, preprocesado
  analysis/           maquetación, columnas, tablas, figuras
  writers/            markdown, docx, xlsx, html, json, txt
build/                spec de PyInstaller y scripts de compilación
tools/                Tesseract portable
tests/                41 pruebas, incluidas las de OCR
```

## Comprobación rápida tras instalar

```bash
pdfx info
```

Debe responder con la ruta de Tesseract, los idiomas disponibles y
`Ventana: disponible`. Si dice `NO ENCONTRADO`, falta la carpeta `tools`.
