"""Servidor MCP `sotica_docs` — generación de archivos de oficina.

Ciclo 1: solo .xlsx (libro de cómputos SOTICA-CM-01). Word y PowerPoint son fase 2.
"""
from __future__ import annotations

import datetime as dt
import json
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..core import control, db, storage
from .registry import Registro, error as _error, ok as _ok

registro = Registro("sotica_docs")

AZUL = "1B365D"      # azul corporativo propuesto (§7.2)
DORADO = "C4A35A"
FUENTE = "Calibri"

_TIT = Font(name=FUENTE, size=11, bold=True, color="FFFFFF")
_H1 = Font(name=FUENTE, size=18, bold=True, color=AZUL)
_NORM = Font(name=FUENTE, size=10)
_NEG = Font(name=FUENTE, size=10, bold=True)
_FILL_TIT = PatternFill("solid", fgColor=AZUL)
_FILL_ACENTO = PatternFill("solid", fgColor=DORADO)
_BORDE = Border(*(Side(style="thin", color="BFBFBF"),) * 4)




def _encabezado(ws, titulos: list[str], fila: int = 1) -> None:
    for col, texto in enumerate(titulos, start=1):
        celda = ws.cell(row=fila, column=col, value=texto)
        celda.font = _TIT
        celda.fill = _FILL_TIT
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = _BORDE
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)


def _anchos(ws, anchos: list[int]) -> None:
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho


def _pie(ws, codigo_doc: str, revision: str) -> None:
    ws.oddFooter.left.text = f"{codigo_doc} Rev. {revision}"
    ws.oddFooter.right.text = "Página &P de &N"


def _hoja_portada(wb, proyecto, base, codigo_doc, revision, formatos_oficiales) -> None:
    ws = wb.create_sheet("Portada")
    _anchos(ws, [28, 60])
    ws["A1"] = "SOTICA"
    ws["A1"].font = _H1
    ws["A2"] = "Libro de cómputos métricos"
    ws["A2"].font = Font(name=FUENTE, size=13, bold=True, color=AZUL)
    ws["A3"].fill = _FILL_ACENTO
    ws["B3"].fill = _FILL_ACENTO

    filas = [
        ("Obra", proyecto["nombre_obra"]),
        ("Código de proyecto", proyecto["codigo"]),
        ("Cliente / ente contratante", proyecto["cliente"] or "—"),
        ("Ubicación", proyecto["ubicacion"] or "—"),
        ("Tipo de documento", "Cómputos métricos"),
        ("Código de documento", codigo_doc),
        ("Revisión", revision),
        ("Fecha", dt.date.today().strftime("%d/%m/%Y")),
        ("Presupuesto base", f"v{base['version']} ({base['tipo']})"),
        ("Moneda / fecha base de precios",
         f"{base['moneda']} / {base['fecha_base']:%d/%m/%Y}"),
        ("Norma rectora", proyecto["norma_rectora"] or "COVENIN 2000"),
        ("Autoría", "SOTICA — sistema SOTICA-COSTOS (apoyo). La firma legal la pone el ingeniero de SOTICA."),
        ("Clasificación", "Confidencial — uso interno SOTICA"),
    ]
    for i, (etiqueta, valor) in enumerate(filas, start=5):
        ws.cell(row=i, column=1, value=etiqueta).font = _NEG
        c = ws.cell(row=i, column=2, value=valor)
        c.font = _NORM
        c.alignment = Alignment(wrap_text=True, vertical="top")

    aviso = ws.cell(
        row=len(filas) + 6, column=1,
        value=("FORMATO SOTICA OFICIAL." if formatos_oficiales else
               "FORMATO SOTICA PROPUESTO — PENDIENTE DE RATIFICACIÓN. "
               "No se cargó plantilla oficial de SOTICA; se aplica el juego propuesto (§7.2)."),
    )
    aviso.font = Font(name=FUENTE, size=10, bold=True, color="9C0006")
    ws.merge_cells(start_row=len(filas) + 6, start_column=1, end_row=len(filas) + 6, end_column=2)
    aviso.alignment = Alignment(wrap_text=True)

    ws2 = ws  # control de revisiones en la misma hoja (SOTICA-DOC-02)
    fila = len(filas) + 9
    ws2.cell(row=fila, column=1, value="Control de revisiones").font = _NEG
    _encabezado(ws2, ["Rev.", "Fecha"], fila=fila + 1)
    ws2.cell(row=fila + 2, column=1, value=revision).font = _NORM
    ws2.cell(row=fila + 2, column=2, value=dt.date.today().strftime("%d/%m/%Y")).font = _NORM


def _hoja_mediciones(wb, filas) -> int:
    """Hoja de medición SOTICA-CM-01: el subtotal es fórmula viva, no número quemado."""
    ws = wb.create_sheet("Hojas de medición")
    _encabezado(ws, ["Código partida", "Descripción", "Unidad", "Referencia de plano",
                     "Despiece del cálculo", "Subtotal", "Etiqueta de dato", "Observación"])
    _anchos(ws, [16, 40, 8, 30, 32, 14, 20, 30])
    fila = 2
    for m in filas:
        ws.cell(row=fila, column=1, value=m["codigo_interno"]).font = _NORM
        ws.cell(row=fila, column=2, value=m["descripcion"]).font = _NORM
        ws.cell(row=fila, column=3, value=m["unidad"]).font = _NORM
        ws.cell(row=fila, column=4, value=m["referencia"]).font = _NORM
        ws.cell(row=fila, column=5, value=m["expresion"]).font = _NORM
        # Fórmula viva cuando el despiece es una expresión aritmética evaluable.
        expr = str(m["expresion"] or "").replace("x", "*").replace(",", ".")
        if expr and all(ch in "0123456789.+-*/() " for ch in expr):
            ws.cell(row=fila, column=6, value=f"={expr}").font = _NORM
        else:
            ws.cell(row=fila, column=6, value=float(m["subtotal"])).font = _NORM
        ws.cell(row=fila, column=6).number_format = "#,##0.00"
        ws.cell(row=fila, column=7, value=m["etiqueta"]).font = _NORM
        ws.cell(row=fila, column=8, value=m["observacion"] or "").font = _NORM
        fila += 1
    if not filas:
        ws.cell(row=2, column=1,
                value="Sin hojas de medición cargadas para el alcance solicitado.").font = _NORM
    return fila


def _hoja_resumen(wb, partidas) -> None:
    ws = wb.create_sheet("Resumen por capítulo")
    _encabezado(ws, ["Capítulo", "Código", "Descripción", "Unidad", "Cantidad",
                     "Etiqueta cantidad", "Fuente de la cantidad", "Responsable"])
    _anchos(ws, [22, 16, 46, 8, 14, 20, 34, 14])
    fila = 2
    for p in partidas:
        valores = [p["capitulo"], p["codigo_interno"], p["descripcion"], p["unidad"],
                   float(p["cantidad"]), p["etiqueta_cantidad"], p["fuente_cantidad"],
                   p["agente_responsable"]]
        for col, valor in enumerate(valores, start=1):
            c = ws.cell(row=fila, column=col, value=valor)
            c.font = _NORM
            c.border = _BORDE
            if col == 5:
                c.number_format = "#,##0.0000"
        fila += 1
    if fila > 2:
        ws.cell(row=fila, column=4, value="TOTAL PARTIDAS").font = _NEG
        ws.cell(row=fila, column=5, value=f"=COUNT(E2:E{fila-1})").font = _NEG


def _hoja_simple(wb, titulo: str, cabeceras: list[str], filas: list[list[Any]],
                 vacio: str) -> None:
    ws = wb.create_sheet(titulo)
    _encabezado(ws, cabeceras)
    _anchos(ws, [max(18, min(60, len(h) * 3)) for h in cabeceras])
    if not filas:
        # Una hoja vacía se declara vacía; no se omite.
        ws.cell(row=2, column=1, value=vacio).font = _NORM
        return
    for i, fila in enumerate(filas, start=2):
        for col, valor in enumerate(fila, start=1):
            c = ws.cell(row=i, column=col, value=valor)
            c.font = _NORM
            c.alignment = Alignment(wrap_text=True, vertical="top")


@registro.herramienta(
    "generar_excel_computos",
    "Genera el libro de cómputos en formato SOTICA-CM-01 (.xlsx) con portada, control de "
    "revisiones, hojas de medición con fórmulas vivas, resumen por capítulo, supuestos e "
    "inconsistencias de planos; lo sube al bucket y lo registra como entregable. Solo SUB-DOC.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "capitulos": {"type": "array", "items": {"type": "string"}},
            "codigos_partida": {"type": "array", "items": {"type": "string"}},
            "revision": {"type": "string", "description": "por defecto 'A'"},
            "titulo": {"type": "string"},
        },
        "required": ["proyecto"],
    },
)
async def generar_excel_computos(args: dict[str, Any]) -> dict[str, Any]:
    revision = args.get("revision") or "A"
    codigo_doc = "SOTICA-CM-01"
    try:
        async with db.transaction() as conn:
            proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
            if proyecto is None:
                return _error(f"No existe la obra '{args['proyecto']}'.")
            base = await control.presupuesto_base(conn, proyecto["id"])
            if base is None:
                return _error("La obra no tiene presupuesto base de control.")

            capitulos = args.get("capitulos") or None
            codigos = args.get("codigos_partida") or None
            partidas = await conn.fetch(
                """
                SELECT * FROM partidas
                 WHERE presupuesto_id = $1
                   AND ($2::text[] IS NULL OR capitulo = ANY($2))
                   AND ($3::text[] IS NULL OR codigo_interno = ANY($3))
                 ORDER BY capitulo, orden, codigo_interno
                """,
                base["id"], capitulos, codigos,
            )
            mediciones = await conn.fetch(
                """
                SELECT p.codigo_interno, p.descripcion, m.referencia, m.expresion,
                       m.subtotal, m.unidad, m.etiqueta, m.observacion
                  FROM mediciones m
                  JOIN partidas p ON p.id = m.partida_id
                 WHERE p.presupuesto_id = $1
                   AND ($2::text[] IS NULL OR p.capitulo = ANY($2))
                   AND ($3::text[] IS NULL OR p.codigo_interno = ANY($3))
                 ORDER BY p.codigo_interno, m.creado_en
                """,
                base["id"], capitulos, codigos,
            )
            faltantes = await conn.fetch(
                "SELECT ambito, descripcion, impacto_estimado, como_obtenerlo, agente "
                "FROM faltantes WHERE proyecto_id = $1 AND estado = 'abierto' ORDER BY creado_en",
                proyecto["id"],
            )
            supuestos = await conn.fetch(
                "SELECT ambito, texto, etiqueta, fuente, impacto_estimado, agente "
                "FROM supuestos WHERE proyecto_id = $1 AND estado <> 'descartado' "
                "ORDER BY creado_en",
                proyecto["id"],
            )
            planos = await conn.fetch(
                "SELECT nombre, metadata, creado_en FROM archivos "
                "WHERE proyecto_id = $1 AND tipo = 'plano' ORDER BY nombre",
                proyecto["id"],
            )

            wb = Workbook()
            wb.remove(wb.active)
            _hoja_portada(wb, proyecto, base, codigo_doc, revision,
                          proyecto["formatos_ratificados"])
            _hoja_simple(
                wb, "Índice de planos", ["Lámina / archivo", "Metadata", "Cargado"],
                [[p["nombre"], json.dumps(p["metadata"], ensure_ascii=False),
                  p["creado_en"].strftime("%d/%m/%Y")] for p in planos],
                "No se cargaron planos para esta obra. Los cómputos de este libro no tienen "
                "plano de respaldo asociado en el sistema.",
            )
            _hoja_simple(
                wb, "Supuestos", ["Ámbito", "Supuesto", "Etiqueta", "Fuente", "Impacto", "Agente"],
                [[s["ambito"], s["texto"], s["etiqueta"], s["fuente"] or "—",
                  s["impacto_estimado"] or "—", s["agente"]] for s in supuestos],
                "Sin supuestos registrados.",
            )
            _hoja_mediciones(wb, mediciones)
            _hoja_resumen(wb, partidas)
            _hoja_simple(
                wb, "Inconsistencias",
                ["Ámbito", "Cantidad no computable / inconsistencia", "Impacto estimado",
                 "Cómo obtener el dato", "Detectado por"],
                [[f["ambito"], f["descripcion"], f["impacto_estimado"] or "—",
                  f["como_obtenerlo"], f["agente"]] for f in faltantes],
                "Sin inconsistencias de planos registradas para esta obra. "
                "La hoja se entrega vacía de forma explícita.",
            )
            for ws in wb.worksheets:
                _pie(ws, codigo_doc, revision)

            buffer = BytesIO()
            wb.save(buffer)
            data = buffer.getvalue()

            nombre = f"{codigo_doc}_Rev-{revision}_{proyecto['codigo']}.xlsx"
            storage_key, sha256, tam = storage.put_bytes(proyecto["codigo"], nombre, data)
            archivo_id = await conn.fetchval(
                """
                INSERT INTO archivos (proyecto_id, tipo, nombre, storage_key, mime, bytes,
                                      sha256, subido_por)
                VALUES ($1,'entregable',$2,$3,
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        $4,$5,'SUB-DOC')
                RETURNING id
                """,
                proyecto["id"], nombre, storage_key, tam, sha256,
            )
            await conn.execute(
                """
                INSERT INTO entregables (proyecto_id, archivo_id, codigo_documento, revision,
                                         titulo, formato, generado_por, formato_oficial)
                VALUES ($1,$2,$3,$4,$5,'xlsx','SUB-DOC',$6)
                ON CONFLICT (proyecto_id, codigo_documento, revision)
                DO UPDATE SET archivo_id = EXCLUDED.archivo_id, titulo = EXCLUDED.titulo,
                              creado_en = now()
                """,
                proyecto["id"], archivo_id, codigo_doc, revision,
                args.get("titulo") or f"Libro de cómputos — {proyecto['nombre_obra']}",
                proyecto["formatos_ratificados"],
            )

            advertencias = []
            if not proyecto["formatos_ratificados"]:
                advertencias.append(
                    "Formato SOTICA propuesto — pendiente de ratificación (no hay plantilla "
                    "oficial cargada)."
                )
            if not planos:
                advertencias.append("No hay planos cargados: el índice de planos sale vacío.")
            if not mediciones:
                advertencias.append(
                    "No hay hojas de medición cargadas: el libro sale sin despiece auditable."
                )

            return _ok({
                "archivo_id": str(archivo_id),
                "codigo_documento": codigo_doc,
                "revision": revision,
                "url_descarga": storage.url_for(storage_key),
                "hojas": [ws.title for ws in wb.worksheets],
                "partidas_incluidas": len(partidas),
                "mediciones_incluidas": len(mediciones),
                "inconsistencias_listadas": len(faltantes),
                "advertencias": advertencias,
            })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


# El servidor MCP se construye en stdio_server.py a partir de este registro.
__all__ = ["registro"]
