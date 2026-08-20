"""Punto de entrada del ejecutable empaquetado.

PyInstaller ejecuta este fichero como script suelto, no como modulo de un
paquete, asi que aqui no puede haber imports relativos.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from pdfx.cli import main
    sys.exit(main())
