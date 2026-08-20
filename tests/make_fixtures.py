"""Genera PDFs de prueba: nativo, escaneado (imagen) y a dos columnas."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Frame, Image as RLImage, ListFlowable, ListItem, PageTemplate, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

HERE = Path(__file__).parent / "data"
HERE.mkdir(parents=True, exist_ok=True)


def make_diagram(path: Path) -> Path:
    """Un esquema sencillo, para comprobar la extraccion de figuras."""
    img = Image.new("RGB", (760, 440), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([40, 60, 250, 200], outline="black", width=5)
    d.text((90, 120), "MOTOR", fill="black")
    d.rectangle([420, 60, 700, 200], outline="black", width=5)
    d.text((490, 120), "REDUCTORA", fill="black")
    d.line([250, 130, 420, 130], fill="black", width=6)
    d.polygon([(420, 130), (400, 120), (400, 140)], fill="black")
    d.ellipse([230, 260, 470, 400], outline="black", width=5)
    d.text((300, 325), "BOMBA P-14", fill="black")
    d.line([350, 200, 350, 260], fill="black", width=6)
    img.save(path)
    return path


TABLE_DATA = [
    ["Referencia", "Descripcion", "Cantidad", "Precio (EUR)"],
    ["SIE-4520B", "Variador de frecuencia 7,5 kW", "2", "1.240,50"],
    ["ABB-7710", "Contactor tripolar 32 A", "12", "86,20"],
    ["FES-0912", "Cilindro neumatico 63x200", "4", "312,00"],
    ["SKF-6205", "Rodamiento rigido de bolas", "24", "18,75"],
]


def styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Cuerpo", parent=ss["BodyText"], fontSize=10.5,
                          leading=14.5, spaceAfter=7))
    ss.add(ParagraphStyle("T1", parent=ss["Heading1"], fontSize=18, spaceBefore=14))
    ss.add(ParagraphStyle("T2", parent=ss["Heading2"], fontSize=13.5, spaceBefore=11))
    return ss


def table_flowable():
    t = Table(TABLE_DATA, colWidths=[70, 200, 55, 75])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde5ef")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def build_native(dest: Path, diagram: Path) -> Path:
    ss = styles()
    doc = SimpleDocTemplate(str(dest), pagesize=A4,
                            leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm,
                            title="Informe de mantenimiento", author="Talleres Munoz S.L.")
    flow = [
        Paragraph("Informe de mantenimiento preventivo", ss["T1"]),
        Paragraph("Planta de envasado - Linea 3", ss["Cuerpo"]),
        Spacer(1, 8),
        Paragraph("1. Alcance de la intervencion", ss["T2"]),
        Paragraph(
            "Se realizo la revision completa del grupo motriz de la linea 3 en las "
            "instalaciones de Talleres Munoz S.L. La intervencion incluyo la "
            "inspeccion del motor principal, la reductora y la bomba de trasiego "
            "P-14, asi como la sustitucion de los elementos de desgaste indicados "
            "en el apartado 3. El responsable de planta, Javier Ortega, valido los "
            "trabajos el mismo dia.",
            ss["Cuerpo"]),
        Paragraph(
            "Para cualquier aclaracion puede contactar con el departamento tecnico "
            "en soporte@talleresmunoz.es o en el telefono 912 445 780.",
            ss["Cuerpo"]),
        Paragraph("2. Observaciones detectadas", ss["T2"]),
        ListFlowable(
            [
                ListItem(Paragraph("Vibracion anomala en el acoplamiento del motor.", ss["Cuerpo"])),
                ListItem(Paragraph("Fuga leve de aceite en la brida de la reductora.", ss["Cuerpo"])),
                ListItem(Paragraph("Desgaste del rodamiento SKF-6205 del eje secundario.", ss["Cuerpo"])),
                ListItem(Paragraph("Variador SIE-4520B con aviso de sobretemperatura.", ss["Cuerpo"])),
            ],
            bulletType="bullet", start="circle", leftIndent=16),
        Spacer(1, 6),
        Paragraph("3. Material sustituido", ss["T2"]),
        table_flowable(),
        Spacer(1, 10),
        Paragraph("4. Esquema del grupo motriz", ss["T2"]),
        RLImage(str(diagram), width=150 * mm, height=87 * mm),
        Paragraph("Figura 1. Disposicion de motor, reductora y bomba P-14.", ss["Cuerpo"]),
        Paragraph("5. Conclusiones", ss["T2"]),
        Paragraph(
            "El equipo queda operativo tras la intervencion. Se recomienda repetir "
            "la medicion de vibraciones dentro de 500 horas de funcionamiento y "
            "programar la sustitucion preventiva del variador antes del proximo "
            "periodo de alta produccion.",
            ss["Cuerpo"]),
    ]
    doc.build(flow)
    return dest


def build_two_columns(dest: Path) -> Path:
    ss = styles()
    doc = SimpleDocTemplate(str(dest), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    width, height = A4
    gap = 10 * mm
    col_w = (width - 36 * mm - gap) / 2
    frames = [
        Frame(18 * mm, 18 * mm, col_w, height - 36 * mm, id="izq"),
        Frame(18 * mm + col_w + gap, 18 * mm, col_w, height - 36 * mm, id="der"),
    ]
    doc.addPageTemplates([PageTemplate(id="dos", frames=frames)])

    parrafo = (
        "El sistema de control supervisa la presion de la linea mediante dos "
        "transductores redundantes instalados en el colector principal. La senal "
        "se filtra con una constante de tiempo de 250 ms antes de entrar en el "
        "lazo de regulacion. "
    )
    flow = [Paragraph("Especificacion tecnica del lazo de presion", ss["T2"])]
    for i in range(8):
        flow.append(Paragraph(f"{parrafo} Bloque {i + 1}.", ss["Cuerpo"]))
    doc.build(flow)
    return dest


def build_scanned(source_pdf: Path, dest: Path, dpi: int = 200,
                  rotate: float = 0.7) -> Path:
    """Rasteriza un PDF y lo reempaqueta como imagenes: simula un escaneo."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(source_pdf))
    pages = []
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=dpi / 72.0, grayscale=True)
        img = bitmap.to_pil().convert("L")
        if rotate:
            img = img.rotate(rotate, resample=Image.BICUBIC, fillcolor=255)
        # ruido suave, como una fotocopia
        import numpy as np
        arr = np.asarray(img, dtype=np.int16)
        rng = np.random.default_rng(7)
        arr = np.clip(arr + rng.normal(0, 6, arr.shape), 0, 255).astype("uint8")
        pages.append(Image.fromarray(arr).convert("RGB"))
    pdf.close()
    pages[0].save(dest, "PDF", save_all=True, append_images=pages[1:],
                  resolution=dpi)
    return dest


def main() -> int:
    diagram = make_diagram(HERE / "_diagrama.png")
    nativo = build_native(HERE / "nativo.pdf", diagram)
    dos_col = build_two_columns(HERE / "dos_columnas.pdf")
    escaneado = build_scanned(nativo, HERE / "escaneado.pdf")
    for p in (nativo, dos_col, escaneado):
        print(f"{p.name:20s} {p.stat().st_size / 1024:8.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
