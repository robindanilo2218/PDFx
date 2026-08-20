"""Rutas y nombres de fichero seguros en Windows y Linux."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_stem(name: str, fallback: str = "documento") -> str:
    stem = _INVALID.sub("_", name).strip(" .")
    if not stem:
        return fallback
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    return stem[:120]


def unique_path(path: Path) -> Path:
    """Evita pisar ficheros existentes: informe.md -> informe (2).md"""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for n in range(2, 1000):
        cand = parent / f"{stem} ({n}){suffix}"
        if not cand.exists():
            return cand
    return parent / f"{stem} ({Path(path).stat().st_mtime_ns}){suffix}"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
