"""Preprocesado de imagen antes del OCR: gris, enderezado y binarizado.

Solo numpy + Pillow: nada de OpenCV, para que el portable siga siendo ligero.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def to_gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.uint8)


def otsu_threshold(gray: np.ndarray) -> int:
    """Umbral global de Otsu."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = gray.size
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = np.where(denom > 0, (mu_t * omega - mu) ** 2 / denom, 0.0)
    return int(np.argmax(sigma_b))


def binarize(gray: np.ndarray) -> np.ndarray:
    """Devuelve booleano: True = tinta (pixel oscuro)."""
    return gray < otsu_threshold(gray)


def _profile_score(ink: np.ndarray) -> float:
    """Varianza del perfil horizontal: maxima cuando los renglones estan rectos."""
    profile = ink.sum(axis=1).astype(np.float64)
    if profile.size < 4:
        return 0.0
    return float(np.var(np.diff(profile)))


def estimate_skew(gray: np.ndarray, max_angle: float = 4.0,
                  step: float = 0.25, work_height: int = 800) -> float:
    """Estima la inclinacion del escaneo en grados (positivo = antihorario)."""
    h, w = gray.shape
    if h < 50 or w < 50:
        return 0.0

    scale = min(1.0, work_height / h)
    if scale < 1.0:
        small = np.asarray(
            Image.fromarray(gray).resize(
                (max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR
            ),
            dtype=np.uint8,
        )
    else:
        small = gray

    ink = binarize(small)
    if ink.mean() < 0.002 or ink.mean() > 0.6:
        return 0.0  # pagina casi vacia o casi negra: no fiar

    base = Image.fromarray((ink * 255).astype(np.uint8))
    best_angle, best_score = 0.0, _profile_score(ink)
    angle = -max_angle
    while angle <= max_angle + 1e-9:
        if abs(angle) > 1e-9:
            rot = base.rotate(angle, resample=Image.BILINEAR, fillcolor=0)
            score = _profile_score(np.asarray(rot, dtype=np.uint8) > 127)
            if score > best_score:
                best_score, best_angle = score, angle
        angle += step
    return best_angle


def deskew(img: Image.Image, max_angle: float = 4.0) -> tuple[Image.Image, float]:
    """Endereza la imagen si detecta inclinacion apreciable."""
    gray = to_gray(img)
    angle = estimate_skew(gray, max_angle=max_angle)
    if abs(angle) < 0.2:
        return img, 0.0
    fill = 255 if img.mode in ("L", "RGB") else None
    rotated = img.rotate(angle, resample=Image.BICUBIC, fillcolor=fill, expand=False)
    return rotated, angle


def autocontrast_gray(img: Image.Image) -> Image.Image:
    """Estira el histograma; ayuda en escaneos lavados o fotocopias flojas."""
    gray = to_gray(img)
    lo, hi = np.percentile(gray, (2, 98))
    if hi - lo < 20:
        return Image.fromarray(gray)
    stretched = np.clip((gray.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255)
    return Image.fromarray(stretched.astype(np.uint8))


def prepare_for_ocr(img: Image.Image, do_deskew: bool = True) -> tuple[Image.Image, float]:
    """Pipeline completo previo al OCR. Devuelve (imagen, angulo_corregido)."""
    angle = 0.0
    work = autocontrast_gray(img)
    if do_deskew:
        work, angle = deskew(work)
    return work, angle
