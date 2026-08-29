# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para PDFx.

Genera una carpeta portable (onedir): arranca rapido y no descomprime nada en
el disco del usuario, que es lo que suele bloquear el antivirus corporativo.

    pyinstaller build/pdfx.spec --noconfirm
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
IS_WIN = sys.platform.startswith("win")

# La carpeta tools/ (Tesseract portable) se copia al lado del ejecutable, no
# dentro del bundle: asi el cliente puede anadir idiomas sin reconstruir nada.
datas = []


def _tcltk_binaries():
    """Librerias de Tcl/Tk que el hook estandar de PyInstaller no recoge.

    Las distribuciones recientes de CPython (incluidas las de uv y las de
    python.org) traen Tcl/Tk 9, con nombres tipo libtcl9.0.so / libtcl9tk9.0.so
    que el hook -pensado para 8.6- no encuentra. Sin ellas el ejecutable
    arranca pero la ventana falla al importar tkinter.
    """
    import glob
    import os
    import sysconfig

    if IS_WIN:
        return []          # en Windows los DLL viven junto a _tkinter y si se recogen

    roots = {sysconfig.get_config_var("prefix"), sys.base_prefix, sys.prefix}
    found = {}
    for root in filter(None, roots):
        for pattern in ("libtcl*.so*", "libtk*.so*"):
            for path in glob.glob(os.path.join(root, "lib", pattern)):
                if os.path.isfile(path):
                    found[os.path.basename(path)] = path
    return [(path, ".") for path in found.values()]


binaries = _tcltk_binaries()
hiddenimports = [
    "PIL._tkinter_finder",
    "openpyxl.cell._writer",
]
excludes = [
    "matplotlib", "scipy", "pandas", "IPython", "notebook", "pytest",
    "setuptools", "pip", "reportlab", "PyQt5", "PySide6", "sqlite3",
    "test", "unittest", "pydoc_data", "lib2to3",
]

a = Analysis(
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFx",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=not IS_WIN,        # en Windows, sin consola negra de fondo
    disable_windowed_traceback=False,
    icon=str(ROOT / "build" / "pdfx.ico") if (ROOT / "build" / "pdfx.ico").exists() else None,
)

# En Windows el ejecutable principal se compila sin consola para que no salga
# una ventana negra detras de la interfaz. El efecto secundario es que pierde
# la salida estandar: sys.stdout pasa a ser None y nada de lo que imprima llega
# a una terminal. Por eso se genera un segundo ejecutable, identico pero de
# consola, para el uso por linea de ordenes, para el .bat de arrastrar y soltar
# y para que el instalador pueda comprobar que lo compilado de verdad funciona.
# Los dos comparten la carpeta _internal, asi que el coste son unos pocos MB.
extra_exes = []
if IS_WIN:
    extra_exes.append(
        EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name="PDFx-consola",
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=False,
            console=True,
            disable_windowed_traceback=False,
            icon=str(ROOT / "build" / "pdfx.ico") if (ROOT / "build" / "pdfx.ico").exists() else None,
        )
    )

coll = COLLECT(
    exe,
    *extra_exes,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDFx",
)
