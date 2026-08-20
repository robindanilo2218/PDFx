"""Parseo de rangos de paginas del estilo '1-3,7,10-'."""

from __future__ import annotations


def parse_page_range(spec: str, total: int) -> list[int]:
    """Devuelve la lista de paginas (1-based) seleccionadas. Vacio -> todas."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(1, total + 1))

    selected: set[int] = set()
    for chunk in spec.replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            start = int(a) if a else 1
            end = int(b) if b else total
        else:
            start = end = int(chunk)
        if start > end:
            start, end = end, start
        for n in range(max(1, start), min(total, end) + 1):
            selected.add(n)
    return sorted(selected) or list(range(1, total + 1))
