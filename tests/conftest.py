import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
sys.path.insert(0, str(ROOT))


def _ensure_fixtures() -> None:
    needed = ["nativo.pdf", "escaneado.pdf", "dos_columnas.pdf"]
    if all((DATA / n).exists() for n in needed):
        return
    subprocess.run([sys.executable, str(ROOT / "tests" / "make_fixtures.py")],
                   check=True, cwd=str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def fixtures():
    _ensure_fixtures()


@pytest.fixture(scope="session")
def nativo() -> Path:
    return DATA / "nativo.pdf"


@pytest.fixture(scope="session")
def escaneado() -> Path:
    return DATA / "escaneado.pdf"


@pytest.fixture(scope="session")
def dos_columnas() -> Path:
    return DATA / "dos_columnas.pdf"


@pytest.fixture(scope="session")
def tesseract_disponible() -> bool:
    from pdfx.engines.ocr import find_tesseract
    return find_tesseract() is not None
