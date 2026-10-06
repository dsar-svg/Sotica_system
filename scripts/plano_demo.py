"""Genera el plano de la demo: lámina A-02, paredes de bloque de planta alta.

    python -m scripts.plano_demo

Escribe docs/demo/plano_A-02_planta_alta.pdf. Es un PDF con capa de texto, como
uno exportado desde CAD, para que `leer_plano_pdf` lo pueda leer. Cantidades
esperadas para la demo:

    muros 2 x (18,00 + 8,00) + 8,00 = 60,00 m  x 2,80 m = 168,00 m2
    - 4 puertas P-1 0,90 x 2,10       =  -7,56 m2
    - 6 ventanas V-1 1,50 x 1,20      = -10,80 m2
    neto                                149,64 m2
"""
from __future__ import annotations

from backend.core.config import BASE_DIR

DESTINO = BASE_DIR / "docs" / "demo" / "plano_A-02_planta_alta.pdf"


def pdf_una_pagina(operaciones: str, ancho: int = 792, alto: int = 612) -> bytes:
    """PDF de una página con Helvetica WinAnsi y el contenido dado; xref calculado a mano."""
    stream = operaciones.encode("cp1252")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] " % (ancho, alto)
        + b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def texto(x: float, y: float, t: str, tam: int = 9) -> str:
    t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 {tam} Tf {x} {y} Td ({t}) Tj ET\n"


def plano() -> bytes:
    # Escala de dibujo: 1 m = 30 pt. Origen del edificio en (60, 200).
    ox, oy, e = 60, 200, 30
    L, A = 18 * e, 8 * e
    ops = ["0 0 0 RG 4 w\n",
           f"{ox} {oy} {L} {A} re S\n",                              # perímetro
           f"{ox + 9 * e} {oy} m {ox + 9 * e} {oy + A} l S\n",       # muro interior eje 2
           "0.5 w\n"]
    # Cotas
    ops += [texto(ox + L / 2 - 30, oy + A + 14, "Muro eje A: 18,00 m"),
            texto(ox + L / 2 - 30, oy - 18, "Muro eje B: 18,00 m"),
            texto(ox - 50, oy + A / 2, "Eje 1: 8,00 m"),
            texto(ox + L + 6, oy + A / 2, "Eje 3: 8,00 m"),
            texto(ox + 9 * e + 6, oy + A / 2 - 20, "Muro interior eje 2: 8,00 m")]
    # Aberturas
    for x in (2, 6, 12, 15):
        ops.append(texto(ox + x * e, oy + 8, "P-1"))
    for x in (1, 4, 7, 10, 13, 16):
        ops.append(texto(ox + x * e, oy + A - 14, "V-1"))
    # Cuadros y notas
    y = 150
    for linea in (
        "CUADRO DE PAREDES",
        "Pared de bloque de arcilla 15 cm, altura libre 2,80 m (de losa a viga)",
        "CUADRO DE ABERTURAS",
        "P-1 puerta 0,90 x 2,10 m - cantidad 4",
        "V-1 ventana 1,50 x 1,20 m - cantidad 6",
        "NOTA: cotas en metros a eje de muro",
        "NOTA: las aberturas se descuentan del área de pared",
    ):
        ops.append(texto(60, y, linea))
        y -= 13
    # Rótulo
    ops.append("1 w 560 30 212 110 re S\n")
    y = 124
    for linea in (
        "PROYECTO: Edificio administrativo - sede regional",
        "OBRA: SOT-2026-014",
        "LAMINA: A-02",
        "CONTENIDO: Planta alta - paredes de bloque",
        "ESCALA: 1:100",
        "FECHA: 01/09/2026",
        "REV: 0",
    ):
        ops.append(texto(566, y, linea, 8))
        y -= 13
    return pdf_una_pagina("".join(ops))


if __name__ == "__main__":
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_bytes(plano())
    print(f"ok  {DESTINO.relative_to(BASE_DIR)}")
