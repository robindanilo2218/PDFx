# PDFx — guía rápida

Para convertir un PDF a texto y poder pegarlo en Claude, ChatGPT o donde sea,
**sin que el documento salga de tu ordenador**.

No hay que instalar nada. No hace falta pedirle permisos a informática.

---

## 1. Abrirlo

| | |
|---|---|
| **Windows** | doble clic en `PDFx.exe` |
| **Linux** | doble clic en `EJECUTAR.sh`, o `./EJECUTAR.sh` desde el terminal |

**La primera vez tarda hasta un minuto en abrirse**, sobre todo desde una
memoria USB. No lo abras dos veces pensando que no ha funcionado: espera.

### Windows te va a dar un susto

Puede salir una pantalla azul que dice **«Windows protegió tu PC»**.

Pulsa **«Más información»** y luego **«Ejecutar de todas formas»**.

Sale porque el programa no está firmado digitalmente, que cuesta dinero. No es
que tenga nada malo.

---

## 2. Convertir un PDF

**Lo más rápido (sólo Windows):** arrastra uno o varios PDF encima de
`ARRASTRA_AQUI_TUS_PDF.bat`. Deja un fichero `.md` al lado de cada PDF y ya está.

**Con la ventana:** pestaña **1. Convertir** → *Añadir PDF...* → marca los
formatos que quieras → *Convertir*.

Si sólo quieres el texto para pegarlo en un asistente, el botón
**«Modo rápido: PDF → .md al lado del original»** hace justo eso y nada más.

---

## 3. ⚠️ Si el PDF es un escaneo, cambia esto

**Es el único ajuste que de verdad importa.** En la ventana, en el panel
**Lectura**, hay un desplegable **OCR** con tres opciones:

```
OCR:  [ auto  ▾ ]     ← cámbialo a  always
```

**Ponlo en `always` siempre que el PDF venga de un escáner o sea una foto.**

### Por qué

En `auto`, PDFx mira si la página ya tiene texto. Si encuentra 60 caracteres o
más, da la página por leída y no la mira más.

El problema: un escaneo con **cabecera, pie de página o número de página** ya
tiene esos 60 caracteres. PDFx se queda con la cabecera y **no lee el resto de
la página**. Te devuelve un documento casi vacío y sin decirte por qué.

Con `always` obliga a leer la imagen entera. Tarda algo más y se acabó el
problema.

> **Regla para no equivocarse:** si al abrir el PDF no puedes seleccionar el
> texto con el ratón, es un escaneo. Pon `always`.

---

## 4. Quitar lo confidencial antes de mandarlo a ningún sitio

Pestaña **2. Revisar y ocultar**.

1. *Analizar documentos*
2. Sale una lista de lo que parece confidencial: empresas, nombres, correos,
   teléfonos, códigos de máquina, IBAN, NIF. Con las páginas donde aparece cada
   cosa y el texto de alrededor, para que veas de qué se trata.
3. Marca lo que no debe salir. Puedes añadir tus propios términos.
4. Marca *Aplicar al convertir*.

En el `.md` esos datos salen como `[CONFIDENCIAL_1]`, `[CONFIDENCIAL_2]`... El
documento se sigue entendiendo, pero ya no dice nombres.

La lista se puede guardar y reutilizar con otros documentos de la misma empresa.

---

## 5. Pegarlo en Claude

Abre el `.md` con el Bloc de notas —o con la pestaña **3. Ver Markdown** del
propio programa— y pégalo en la conversación.

**Por qué merece la pena en lugar de subir el PDF:** un informe de dos páginas
con una tabla y una imagen gasta entre 3.000 y 6.000 tokens si subes el PDF,
porque el asistente lo procesa como una imagen, página a página. El mismo
informe en `.md` son unos 520. **Entre 6 y 10 veces menos.**

Y de paso el asistente lee mejor, porque le llega texto en vez de fotos de
texto.

---

## 6. Si algo va mal

| Qué ves | Qué pasa |
|---|---|
| **Los escaneados salen vacíos** | Casi siempre es el OCR en `auto`: ve al punto 3. Si aun así sale vacío, falta la carpeta `tools`: vuelve a copiar la carpeta `PDFx` entera desde el origen. |
| **No arranca desde el USB** | Algunos ordenadores de empresa bloquean los programas en memorias USB. Copia la carpeta `PDFx` al disco duro, por ejemplo a Documentos, y ábrela desde ahí. |
| **Se abre y se cierra sola** | Has copiado sólo el ejecutable. Hace falta la carpeta **entera**: sin `_internal` y `tools` no arranca. |
| **Linux: «Permission denied»** | La carpeta ha perdido el permiso de ejecución. Las órdenes exactas están en `LEEME_PRIMERO.txt`, dentro de la carpeta. |
| **Faltan símbolos raros en el texto** | El OCR descarta en silencio lo que no ve claro. Sube la *Calidad OCR* de 300 a 400 o 600 ppp y vuelve a intentarlo. |

---

## 7. Lo que este programa no hace

**No se conecta a internet. Nunca.** No es una promesa comercial: el programa no
tiene capacidad de hacerlo. Puedes desconectar el cable o el wifi y funciona
exactamente igual. Ningún documento que abras aquí sale de tu ordenador.

Lo que hagas después con el `.md` ya es cosa tuya: si lo pegas en un asistente,
ese texto sí viaja. Por eso está el punto 4.

---

PDFx es software libre bajo licencia GPL v3.
Copyright (C) 2026 Robin Gregorio · <https://github.com/robindanilo2218/PDFx>
