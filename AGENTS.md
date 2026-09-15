# AGENTS.md — PDFx (conversor de PDF 100% offline)

Estás en el código de **PDFx**: conversor de PDF (incluidos escaneados, vía OCR portátil) a Markdown/Word/Excel/HTML/JSON, con redacción/saneado integrado. Cero llamadas de red en todo el programa.

`PDFx/` es su **propio repo git**, distinto del repo externo `hashchat-main` en el que vive en disco (remoto: `github.com/robindanilo2218/PDFx`). A diferencia de MDx, está correctamente ignorado en el `.gitignore` externo (`/PDFx/`) — no hay riesgo de doble-tracking. Aun así, **usa siempre `cd PDFx` primero** y su propio `git status`/`git add`/`git commit`/`git push`.

➡️ **Reglas canónicas obligatorias:** carga el skill `pdfx-architecture` (Skill tool) o léelo en [`../.claude/skills/pdfx-architecture/SKILL.md`](../.claude/skills/pdfx-architecture/SKILL.md).
Referencia primaria: [`README.md`](README.md).

## Recordatorios críticos (no exhaustivo — lee las reglas completas)
- **Invariante dura: cero llamadas de red.** No existe ningún import de `urllib`/`requests`/`socket`/`http.client` bajo `pdfx/` — no lo cambies sin un pedido explícito del usuario.
- `Settings.ocr` por defecto es `"auto"`: una página escaneada con solo encabezado/pie puede superar el umbral de caracteres nativos y nunca rasterizarse para OCR, devolviendo un documento casi vacío sin error. Limitación de diseño conocida, no la "arregles" de pasada.
- Capas estrictas: `engines/` (I/O) → `analysis/` (puro, sin I/O) → `model.py` (el IR) → `writers/` (IR → archivo).
- `config.Settings`/`config.RedactionSettings` es la única fuente de verdad para opciones nuevas.
- Builds portables con PyInstaller **onedir** vía `build/setup-pdfx-windows.ps1`/`build/setup-pdfx-linux.sh`; no saltees el paso 7 (auto-verificación) al validar un cambio real.
- No toques `hashchat/`, `hashchat-dev/`, `Tiendas_bussiness/`, `md_crgm_app-main/` ni los proyectos congelados (crgm, morg, shipping, spa).
- Licencia GPL-3.0-only; nuevas dependencias permisivas o compatibles con GPL (nunca AGPL — por eso `pypdfium2` en vez de PyMuPDF).
