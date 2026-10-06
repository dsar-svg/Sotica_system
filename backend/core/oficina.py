"""Documentos Word y PowerPoint en formato SOTICA (§7).

Funciones puras: reciben el contenido ya redactado por SUB-DOC y devuelven los bytes del
archivo. La forma la pone el sistema (portada SOTICA-DOC-01, control de revisiones
SOTICA-DOC-02, secciones obligatorias de cada tipo, tipografía, márgenes, pie con código y
página); el contenido lo redacta el agente. Si falta una sección obligatoria, se incluye
marcada como PENDIENTE DE CONFIRMACIÓN en vez de omitirla.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptColor
from pptx.util import Inches
from pptx.util import Pt as PptPt

AZUL = RGBColor(0x1B, 0x36, 0x5D)
DORADO = RGBColor(0xC4, 0xA3, 0x5A)
FUENTE = "Calibri"
PENDIENTE = "PENDIENTE DE CONFIRMACIÓN — no hay información para esta sección en este ciclo."

# §7.2. Los códigos MEM, DIC, OBS y PRS no están en la solicitud: son propuestos.
TIPOS: dict[str, dict[str, Any]] = {
    "informe_avance": {
        "codigo": "SOTICA-INF-01", "nombre": "Informe de avance de obra",
        "secciones": ["Resumen ejecutivo", "Avance físico", "Avance financiero", "Recursos",
                      "Problemas", "Seguridad", "Próximo período", "Anexos"]},
    "informe_tecnico": {
        "codigo": "SOTICA-INF-02", "nombre": "Informe técnico",
        "secciones": ["Objeto", "Antecedentes", "Normativa", "Análisis", "Conclusiones",
                      "Recomendaciones", "Anexos"]},
    "propuesta_comercial": {
        "codigo": "SOTICA-COM-01", "nombre": "Propuesta comercial",
        "secciones": ["Carta de presentación", "Comprensión del alcance", "Metodología",
                      "Organigrama", "Plazo", "Precio", "Exclusiones", "Validez de la oferta",
                      "Anexos"]},
    "memoria_presupuesto": {
        "codigo": "SOTICA-MEM-01", "nombre": "Memoria de presupuesto y supuestos",
        "secciones": ["Objeto", "Alcance", "Bases del presupuesto", "Supuestos",
                      "Fuentes de precio", "Exclusiones", "Pendientes de confirmación",
                      "Quién hizo qué"]},
    "dictamen": {
        "codigo": "SOTICA-DIC-01", "nombre": "Dictamen de especialidad",
        "secciones": ["Objeto", "Documentos revisados", "Análisis", "Conclusiones", "Riesgos",
                      "Pendientes"]},
    "observaciones_pliego": {
        "codigo": "SOTICA-OBS-01", "nombre": "Observaciones al pliego y matriz de riesgos",
        "secciones": ["Objeto", "Documentos revisados", "Observaciones", "Matriz de riesgos",
                      "Cláusulas que mandan", "Recomendaciones"]},
}


def _clave(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


def ordenar_secciones(tipo: str, secciones: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    """Secciones en el orden del formato; las obligatorias que falten van como pendientes.
    Las secciones extra del agente se agregan antes de Anexos. Devuelve (secciones, faltantes)."""
    dadas = {_clave(s["titulo"]): s for s in secciones}
    plantilla = TIPOS[tipo]["secciones"]
    claves_plantilla = {_clave(t) for t in plantilla}
    extras = [s for s in secciones if _clave(s["titulo"]) not in claves_plantilla]
    salida, faltantes = [], []
    for titulo in plantilla:
        if titulo == "Anexos":
            salida += extras
            extras = []
        s = dadas.get(_clave(titulo))
        if s is None or not (s.get("contenido") or s.get("tabla")):
            faltantes.append(titulo)
            s = {"titulo": titulo, "contenido": PENDIENTE}
        salida.append({**s, "titulo": titulo})
    return salida + extras, faltantes


def _parrafo_con_negritas(p, texto: str) -> None:
    for i, trozo in enumerate(re.split(r"\*\*", texto)):
        if trozo:
            p.add_run(trozo).bold = bool(i % 2)


def _campo_pagina(parrafo) -> None:
    run = parrafo.add_run()
    for tipo, texto in (("begin", None), (None, "PAGE"), ("end", None)):
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = texto
        run._r.append(el)


def _tabla(doc, cabeceras: list[str], filas: list[list[Any]]) -> None:
    t = doc.add_table(rows=1, cols=len(cabeceras))
    t.style = "Table Grid"
    for celda, texto in zip(t.rows[0].cells, cabeceras):
        celda.text = ""
        run = celda.paragraphs[0].add_run(str(texto))
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        sombra = OxmlElement("w:shd")
        sombra.set(qn("w:val"), "clear")
        sombra.set(qn("w:fill"), "1B365D")
        celda._tc.get_or_add_tcPr().append(sombra)
    for fila in filas:
        celdas = t.add_row().cells
        for celda, valor in zip(celdas, fila):
            celda.text = "" if valor is None else str(valor)


def documento_word(tipo: str, proyecto: dict[str, Any], titulo: str, secciones: list[dict],
                   revision: str, formato_oficial: bool,
                   revisiones: list[list[str]] | None = None) -> tuple[bytes, list[str]]:
    """Devuelve (bytes del .docx, secciones obligatorias que quedaron pendientes)."""
    info = TIPOS[tipo]
    ordenadas, faltantes = ordenar_secciones(tipo, secciones)
    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = FUENTE
    estilo.font.size = Pt(11)
    estilo.element.rPr.rFonts.set(qn("w:eastAsia"), FUENTE)
    for nombre in ("Heading 1", "Heading 2", "Title"):
        doc.styles[nombre].font.name = FUENTE
        doc.styles[nombre].font.color.rgb = AZUL
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)   # A4
    sec.orientation = WD_ORIENT.PORTRAIT
    for lado in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, lado, Cm(2))
    pie = sec.footer.paragraphs[0]
    pie.text = f"{info['codigo']} Rev. {revision} · {proyecto['codigo']} · Confidencial · Página "
    _campo_pagina(pie)

    # SOTICA-DOC-01 Portada
    marca = doc.add_paragraph()
    r = marca.add_run("SOTICA")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(32), AZUL
    linea = doc.add_paragraph()
    r = linea.add_run("━" * 30)
    r.font.color.rgb = DORADO
    doc.add_paragraph(titulo, style="Title")
    hoy = dt.date.today().strftime("%d/%m/%Y")
    _tabla(doc, ["Campo", "Dato"], [
        ["Obra", proyecto["nombre_obra"]],
        ["Código de proyecto", proyecto["codigo"]],
        ["Cliente / ente contratante", proyecto.get("cliente") or "—"],
        ["Ubicación", proyecto.get("ubicacion") or "—"],
        ["Tipo de documento", info["nombre"]],
        ["Código de documento", info["codigo"]],
        ["Revisión", revision],
        ["Fecha", hoy],
        ["Autoría", "SOTICA — sistema SOTICA-COSTOS (apoyo). La firma legal la pone el "
                    "ingeniero de SOTICA."],
        ["Clasificación", "Confidencial — uso interno SOTICA"],
    ])
    aviso = doc.add_paragraph()
    r = aviso.add_run("FORMATO SOTICA OFICIAL." if formato_oficial else
                      "FORMATO SOTICA PROPUESTO — PENDIENTE DE RATIFICACIÓN.")
    r.bold, r.font.color.rgb = True, RGBColor(0x9C, 0x00, 0x06)

    # SOTICA-DOC-02 Control de revisiones
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_heading("Control de revisiones", level=1)
    _tabla(doc, ["Rev.", "Fecha", "Descripción", "Preparó", "Revisó"],
           revisiones or [[revision, hoy, "Emisión inicial", "SOTICA-COSTOS (SUB-DOC)",
                           "Pendiente — ingeniero de SOTICA"]])

    for i, s in enumerate(ordenadas, start=1):
        doc.add_heading(f"{i}. {s['titulo']}", level=1)
        for bloque in re.split(r"\n\s*\n", (s.get("contenido") or "").strip()):
            for renglon in bloque.splitlines():
                renglon = renglon.strip()
                if not renglon:
                    continue
                if renglon.startswith(("- ", "• ", "* ")):
                    _parrafo_con_negritas(doc.add_paragraph(style="List Bullet"), renglon[2:])
                else:
                    _parrafo_con_negritas(doc.add_paragraph(), renglon)
        if s.get("tabla"):
            _tabla(doc, s["tabla"]["cabeceras"], s["tabla"]["filas"])
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue(), faltantes


def presentacion(proyecto: dict[str, Any], titulo: str, diapositivas: list[dict], codigo: str,
                 revision: str, formato_oficial: bool) -> bytes:
    """PowerPoint 16:9: portada SOTICA, una diapositiva por tema (título + viñetas), cierre."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    azul, dorado = PptColor(0x1B, 0x36, 0x5D), PptColor(0xC4, 0xA3, 0x5A)

    def texto(slide, x, y, w, h, contenido, tam, color=azul, negrita=False):
        caja = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
        caja.word_wrap = True
        for i, linea in enumerate(contenido if isinstance(contenido, list) else [contenido]):
            p = caja.paragraphs[0] if i == 0 else caja.add_paragraph()
            p.text = linea
            p.font.size, p.font.name, p.font.bold = PptPt(tam), FUENTE, negrita
            p.font.color.rgb = color

    def pie(slide, n):
        texto(slide, 0.5, 7.0, 12.3, 0.4,
              f"{codigo} Rev. {revision} · {proyecto['codigo']} · Confidencial · {n}", 10,
              PptColor(0x59, 0x59, 0x59))

    def franja(slide):
        barra = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.25))
        barra.fill.solid()
        barra.fill.fore_color.rgb = dorado
        barra.line.fill.background()

    vacio = prs.slide_layouts[6]
    s = prs.slides.add_slide(vacio)
    franja(s)
    texto(s, 0.8, 1.5, 11.5, 1.0, "SOTICA", 44, negrita=True)
    texto(s, 0.8, 2.6, 11.5, 1.2, titulo, 30)
    texto(s, 0.8, 4.0, 11.5, 1.6, [proyecto["nombre_obra"], proyecto["codigo"],
                                   dt.date.today().strftime("%d/%m/%Y")], 18,
          PptColor(0x33, 0x33, 0x33))
    if not formato_oficial:
        texto(s, 0.8, 6.0, 11.5, 0.5, "Formato SOTICA propuesto — pendiente de ratificación",
              12, PptColor(0x9C, 0x00, 0x06), True)
    pie(s, 1)
    for n, d in enumerate(diapositivas, start=2):
        s = prs.slides.add_slide(vacio)
        franja(s)
        texto(s, 0.6, 0.5, 12.0, 0.9, d["titulo"], 28, negrita=True)
        texto(s, 0.8, 1.6, 11.8, 5.2, [f"• {v}" for v in d.get("vinetas") or []], 18,
              PptColor(0x22, 0x22, 0x22))
        pie(s, n)
    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
