"""Servidor MCP `sotica_docs` — generación de archivos de oficina.

Excel (cómputos, presupuesto, Gantt), Word y PowerPoint en formato SOTICA (§7).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..core import apu, control, db, oficina, storage
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


def _hoja_portada(wb, proyecto, base, codigo_doc, revision, formatos_oficiales,
                  titulo: str = "Libro de cómputos métricos",
                  tipo_documento: str = "Cómputos métricos") -> None:
    ws = wb.create_sheet("Portada")
    _anchos(ws, [28, 60])
    ws["A1"] = "SOTICA"
    ws["A1"].font = _H1
    ws["A2"] = titulo
    ws["A2"].font = Font(name=FUENTE, size=13, bold=True, color=AZUL)
    ws["A3"].fill = _FILL_ACENTO
    ws["B3"].fill = _FILL_ACENTO

    filas = [
        ("Obra", proyecto["nombre_obra"]),
        ("Código de proyecto", proyecto["codigo"]),
        ("Cliente / ente contratante", proyecto["cliente"] or "—"),
        ("Ubicación", proyecto["ubicacion"] or "—"),
        ("Tipo de documento", tipo_documento),
        ("Código de documento", codigo_doc),
        ("Revisión", revision),
        ("Fecha", dt.date.today().strftime("%d/%m/%Y")),
        ("Presupuesto de origen",
         f"v{base['version']} ({base['tipo']}) — "
         + ("base de control" if base["es_base_control"] else f"{base['estado']}, no aprobado")),
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
            "origen": {
                "type": "string", "enum": ["auto", "borrador", "base"],
                "description": "De qué presupuesto salen las cantidades. auto (por defecto): "
                               "el borrador con los cómputos en curso si existe; si no, la "
                               "base de control.",
            },
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
            base = await control.presupuesto_por_origen(
                conn, proyecto["id"], args.get("origen") or "auto"
            )
            if base is None:
                return _error("La obra no tiene presupuesto del que tomar cantidades.")

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
                "presupuesto_origen": {"version": base["version"], "estado": base["estado"],
                                       "es_base_control": base["es_base_control"]},
                "url_descarga": storage.url_for(storage_key),
                "hojas": [ws.title for ws in wb.worksheets],
                "partidas_incluidas": len(partidas),
                "mediciones_incluidas": len(mediciones),
                "inconsistencias_listadas": len(faltantes),
                "advertencias": advertencias,
            })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_DET = "'Detalle de partidas'"


async def _guardar_entregable(conn, proyecto, wb, codigo_doc: str, revision: str,
                              titulo: str) -> tuple[Any, str]:
    for ws in wb.worksheets:
        _pie(ws, codigo_doc, revision)
    buffer = BytesIO()
    wb.save(buffer)
    return await _registrar_entregable(conn, proyecto, buffer.getvalue(), "xlsx",
                                       codigo_doc, revision, titulo)


async def _registrar_entregable(conn, proyecto, datos: bytes, formato: str, codigo_doc: str,
                                revision: str, titulo: str) -> tuple[Any, str]:
    nombre = f"{codigo_doc}_Rev-{revision}_{proyecto['codigo']}.{formato}"
    storage_key, sha256, tam = storage.put_bytes(proyecto["codigo"], nombre, datos)
    archivo_id = await conn.fetchval(
        """
        INSERT INTO archivos (proyecto_id, tipo, nombre, storage_key, mime, bytes, sha256,
                              subido_por)
        VALUES ($1,'entregable',$2,$3,$4,$5,$6,'SUB-DOC') RETURNING id
        """,
        proyecto["id"], nombre, storage_key, _MIME[formato], tam, sha256,
    )
    await conn.execute(
        """
        INSERT INTO entregables (proyecto_id, archivo_id, codigo_documento, revision, titulo,
                                 formato, generado_por, formato_oficial)
        VALUES ($1,$2,$3,$4,$5,$6,'SUB-DOC',$7)
        ON CONFLICT (proyecto_id, codigo_documento, revision)
        DO UPDATE SET archivo_id = EXCLUDED.archivo_id, titulo = EXCLUDED.titulo,
                      formato = EXCLUDED.formato, creado_en = now()
        """,
        proyecto["id"], archivo_id, codigo_doc, revision, titulo, formato,
        proyecto["formatos_ratificados"],
    )
    return archivo_id, storage.url_for(storage_key)


def _celdas(ws, fila: int, valores: list[Any], formatos: dict[int, str] | None = None) -> None:
    for col, valor in enumerate(valores, start=1):
        c = ws.cell(row=fila, column=col, value=valor)
        c.font = _NORM
        c.border = _BORDE
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if formatos and col in formatos:
            c.number_format = formatos[col]


def _hoja_detalle(wb, partidas) -> int:
    """Detalle de partidas. El monto se separa en firme y pendiente con fórmulas vivas:
    un precio pendiente de confirmación está en el libro, pero no en el total firme."""
    ws = wb.create_sheet("Detalle de partidas")
    _encabezado(ws, ["Capítulo", "Código", "COVENIN", "Descripción", "Unidad", "Cantidad",
                     "Etiqueta cantidad", "Precio unitario", "Etiqueta precio",
                     "Fuente del precio", "Monto firme", "Monto pendiente de confirmación"])
    _anchos(ws, [18, 12, 10, 44, 8, 13, 18, 14, 22, 44, 16, 18])
    fila = 2
    for p in partidas:
        precio = float(p["precio_unitario"]) if p["precio_unitario"] is not None else None
        _celdas(ws, fila, [
            p["capitulo"], p["codigo_interno"], p["codigo_covenin"] or "", p["descripcion"],
            p["unidad"], float(p["cantidad"]), p["etiqueta_cantidad"], precio,
            p["etiqueta_precio"] or "SIN PRECIO",
            p["fuente_precio"] or "Sin precio cargado: la partida no suma al presupuesto.",
            f'=IF(OR(I{fila}="SIN PRECIO",I{fila}="pendiente_confirmacion"),0,F{fila}*H{fila})',
            f'=IF(I{fila}="pendiente_confirmacion",F{fila}*H{fila},0)',
        ], {6: "#,##0.00", 8: "#,##0.00", 11: "#,##0.00", 12: "#,##0.00"})
        fila += 1
    if fila == 2:
        ws.cell(row=2, column=1, value="El presupuesto no tiene partidas.").font = _NORM
        return fila
    ws.cell(row=fila, column=10, value="TOTAL COSTO DIRECTO").font = _NEG
    for col in ("K", "L"):
        c = ws[f"{col}{fila}"]
        c.value, c.font, c.number_format = f"=SUM({col}2:{col}{fila-1})", _NEG, "#,##0.00"
    return fila


def _hoja_resumen_montos(wb, capitulos: list[str], fila_total_detalle: int) -> None:
    ws = wb.create_sheet("Resumen por capítulo")
    _encabezado(ws, ["Capítulo", "Monto firme", "Monto pendiente de confirmación"])
    _anchos(ws, [34, 20, 30])
    fila = 2
    for cap in capitulos:
        _celdas(ws, fila, [
            cap,
            f"=SUMIF({_DET}!A:A,A{fila},{_DET}!K:K)",
            f"=SUMIF({_DET}!A:A,A{fila},{_DET}!L:L)",
        ], {2: "#,##0.00", 3: "#,##0.00"})
        fila += 1
    if fila > 2:
        ws.cell(row=fila, column=1, value="TOTAL COSTO DIRECTO").font = _NEG
        for col in ("B", "C"):
            c = ws[f"{col}{fila}"]
            c.value, c.font, c.number_format = f"=SUM({col}2:{col}{fila-1})", _NEG, "#,##0.00"


@registro.herramienta(
    "generar_excel_presupuesto",
    "Genera el presupuesto de obra en formato SOTICA-PRE-01 (.xlsx): portada, resumen por "
    "capítulo, detalle de partidas, carpeta de APU con la evidencia de cada precio, indirectos "
    "y notas. Los montos son fórmulas vivas y separan lo firme de lo pendiente de "
    "confirmación; una partida sin precio aparece pero no suma. Lo sube al bucket y lo "
    "registra como entregable. Solo SUB-DOC.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "origen": {
                "type": "string", "enum": ["auto", "borrador", "base"],
                "description": "auto (por defecto): el borrador en curso si existe; si no, "
                               "la base de control.",
            },
            "revision": {"type": "string", "description": "por defecto 'A'"},
            "titulo": {"type": "string"},
        },
        "required": ["proyecto"],
    },
)
async def generar_excel_presupuesto(args: dict[str, Any]) -> dict[str, Any]:
    revision = args.get("revision") or "A"
    codigo_doc = "SOTICA-PRE-01"
    try:
        async with db.transaction() as conn:
            proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
            if proyecto is None:
                return _error(f"No existe la obra '{args['proyecto']}'.")
            base = await control.presupuesto_por_origen(
                conn, proyecto["id"], args.get("origen") or "auto"
            )
            if base is None:
                return _error("La obra no tiene presupuesto del que tomar partidas.")

            partidas = await conn.fetch(
                "SELECT * FROM partidas WHERE presupuesto_id = $1 "
                "ORDER BY capitulo, orden, codigo_interno",
                base["id"],
            )
            renglones = await conn.fetch(
                """
                SELECT p.codigo_interno, r.* FROM apu_renglones r
                  JOIN partidas p ON p.id = r.partida_id
                 WHERE p.presupuesto_id = $1
                 ORDER BY p.capitulo, p.orden, p.codigo_interno, r.tipo, r.descripcion
                """,
                base["id"],
            )
            faltantes = await conn.fetch(
                "SELECT ambito, descripcion, impacto_estimado, como_obtenerlo FROM faltantes "
                "WHERE proyecto_id = $1 AND estado = 'abierto' ORDER BY creado_en",
                proyecto["id"],
            )

            wb = Workbook()
            wb.remove(wb.active)
            _hoja_portada(wb, proyecto, base, codigo_doc, revision,
                          proyecto["formatos_ratificados"],
                          titulo="Presupuesto de obra", tipo_documento="Presupuesto")
            capitulos = list(dict.fromkeys(p["capitulo"] for p in partidas))
            ws_resumen_pos = len(wb.worksheets)
            fila_total = _hoja_detalle(wb, partidas)
            _hoja_resumen_montos(wb, capitulos, fila_total)
            wb.move_sheet("Resumen por capítulo", ws_resumen_pos - len(wb.worksheets) + 1)

            _hoja_simple(
                wb, "APU",
                ["Partida", "Tipo", "Insumo", "Unidad", "Cantidad", "Rendimiento (und/día)",
                 "Desperdicio %", "Precio", "Aporte al precio unitario", "Origen", "Proveedor",
                 "Enlace", "Fecha de consulta", "Etiqueta de dato", "Registrado por"],
                [[r["codigo_interno"], r["tipo"], r["descripcion"], r["unidad"],
                  float(r["cantidad"]),
                  float(r["rendimiento"]) if r["rendimiento"] is not None else "",
                  float(r["desperdicio_pct"] or 0), float(r["precio_unitario"]),
                  float(r["subtotal"]), r["origen"], r["proveedor"] or "—", r["enlace"] or "—",
                  r["fecha_fuente"].strftime("%d/%m/%Y") if r["fecha_fuente"] else "—",
                  r["etiqueta"], r["registrado_por"]] for r in renglones],
                "Ninguna partida tiene APU cargado.",
            )

            sin_precio = [p["codigo_interno"] for p in partidas if p["precio_unitario"] is None]
            pendientes = [p["codigo_interno"] for p in partidas
                          if p["etiqueta_precio"] == "pendiente_confirmacion"]
            sin_fcas = sorted({r["codigo_interno"] for r in renglones if r["tipo"] == "mano_obra"}
                              & {p["codigo_interno"] for p in partidas
                                 if p["apu_fcas_pct"] is None})
            # Filas 2..8: CD, adm (sobre CD), subtotal, utilidad (sobre CD+adm), subtotal,
            # impuesto (sobre subtotal), precio de oferta. Todo con fórmulas vivas.
            pcts = {"adm": base["adm_pct"], "uti": base["utilidad_pct"],
                    "imp": base["impuesto_pct"]}
            faltan = [n for n, k in (("administración", "adm"), ("utilidad", "uti"),
                                     ("impuesto", "imp")) if pcts[k] is None]
            fuente = base["fuente_indirectos"] or ""

            def _linea(nombre, clave, sobre):
                if pcts[clave] is None:
                    return [nombre, "—", "PENDIENTE: lo define SOTICA o el pliego. "
                                         "No se aplica ningún porcentaje."]
                return [f"{nombre} ({float(pcts[clave]):g} %)",
                        f"=B{sobre}*{float(pcts[clave]) / 100}", fuente]

            _hoja_simple(
                wb, "Indirectos", ["Concepto", "Valor", "Estado / fuente"],
                [["Costo directo firme", f"={_DET}!K{fila_total}" if partidas else 0,
                  "Suma de partidas con precio sustentado."],
                 _linea("Administración y gastos generales", "adm", 2),
                 ["Subtotal (costo directo + administración)", "=B2+N(B3)", ""],
                 _linea("Utilidad e imprevistos", "uti", 4),
                 ["Subtotal antes de impuestos", "=B4+N(B5)", ""],
                 _linea("Impuesto", "imp", 6),
                 ["PRECIO DE OFERTA",
                  "=B6+N(B7)" if not faltan else "—",
                  "Decisión final de precio: SOTICA (§12)." if not faltan else
                  f"No calculable: falta {', '.join(faltan)}."]],
                "",
            )
            for fila in range(2, 9):
                wb["Indirectos"].cell(row=fila, column=2).number_format = "#,##0.00"
            wb["Indirectos"]["A8"].font = _NEG
            wb["Indirectos"]["B8"].font = _NEG
            notas = [["Alcance",
                      "Costo directo y precio de oferta (hoja Indirectos)." if not faltan else
                      "Este libro presenta COSTO DIRECTO. No es precio de oferta: falta "
                      f"{', '.join(faltan)} (hoja Indirectos)."]]
            if not base["es_base_control"]:
                notas.append(["Estado", f"Presupuesto v{base['version']} en {base['estado']}: "
                                        "no está aprobado ni es base de control de obra."])
            if sin_precio:
                notas.append(["Partidas sin precio", ", ".join(sin_precio)
                              + ". Aparecen en el detalle pero no suman."])
            if pendientes:
                notas.append(["Precios pendientes de confirmación", ", ".join(pendientes)
                              + ". Falta evidencia (proveedor, enlace o fecha) en algún insumo; "
                                "su monto va en columna aparte y no entra al total firme."])
            de_internet = sorted({r["codigo_interno"] for r in renglones
                                  if r["origen"] == "consulta_internet"})
            if de_internet:
                notas.append(["Precios aproximados de internet", ", ".join(de_internet)
                              + ". Tienen insumos con precio hallado en la web (hoja APU, con "
                                "enlace y fecha). Son referenciales: suman al total, pero deben "
                                "confirmarse con cotización de proveedor antes de ofertar."])
            if sin_fcas:
                notas.append(["FCAS no definido", ", ".join(sin_fcas)
                              + ". La mano de obra va sin recargo hasta que SOTICA indique el FCAS."])
            notas += [[f"Faltante — {f['ambito']}",
                       f"{f['descripcion']} Impacto: {f['impacto_estimado'] or 'no estimado'}. "
                       f"Cómo obtenerlo: {f['como_obtenerlo']}"] for f in faltantes]
            _hoja_simple(wb, "Notas", ["Tema", "Nota"], notas, "")
            wb["Notas"].column_dimensions["B"].width = 110
            wb["Indirectos"].column_dimensions["A"].width = 36
            wb["Indirectos"].column_dimensions["C"].width = 70

            firme = sum(float(p["monto"] or 0) for p in partidas
                        if p["precio_unitario"] is not None
                        and p["etiqueta_precio"] != "pendiente_confirmacion")
            pendiente = sum(float(p["monto"] or 0) for p in partidas
                            if p["etiqueta_precio"] == "pendiente_confirmacion")

            archivo_id, url = await _guardar_entregable(
                conn, proyecto, wb, codigo_doc, revision,
                args.get("titulo") or f"Presupuesto de obra — {proyecto['nombre_obra']}",
            )
            return _ok({
                "archivo_id": str(archivo_id),
                "codigo_documento": codigo_doc,
                "revision": revision,
                "presupuesto_origen": {"version": base["version"], "estado": base["estado"],
                                       "es_base_control": base["es_base_control"]},
                "url_descarga": url,
                "hojas": [ws.title for ws in wb.worksheets],
                "moneda": base["moneda"],
                "partidas_incluidas": len(partidas),
                "renglones_apu": len(renglones),
                "costo_directo_firme": round(firme, 2),
                "monto_pendiente_confirmacion": round(pendiente, 2),
                "partidas_sin_precio": sin_precio,
                "partidas_con_precio_pendiente": pendientes,
                "partidas_con_precios_de_internet": de_internet,
                "precio_de_oferta": (apu.precio_oferta(firme, pcts["adm"], pcts["uti"], pcts["imp"])
                                     if not faltan else
                                     f"no calculable: falta {', '.join(faltan)}"),
                "advertencias": [n[0] + ": " + n[1] for n in notas[:6]],
            })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


def _rendimiento_dia(partida) -> float | None:
    """Unidades por día: el del APU si existe; si no, el primer número del rendimiento declarado
    en la planificación ("60 m3/día, 1 retroexcavadora" -> 60)."""
    if partida["apu_rendimiento"]:
        return float(partida["apu_rendimiento"])
    m = re.search(r"\d+(?:[.,]\d+)?", partida["rendimiento_declarado"] or "")
    return float(m.group(0).replace(",", ".")) if m else None


def _dias_habiles(inicio: dt.date, fin: dt.date) -> int:
    """Igual que NETWORKDAYS de Excel: lunes a viernes, ambos extremos incluidos."""
    return sum(1 for i in range((fin - inicio).days + 1)
               if (inicio + dt.timedelta(days=i)).weekday() < 5)


@registro.herramienta(
    "generar_gantt",
    "Genera el cronograma de obra SOTICA-PLA-01 (.xlsx): portada, Gantt por semanas, curva S, premisas "
    "de productividad e hitos contractuales, a partir de la planificación del presupuesto base. "
    "Verifica que el Gantt no contradiga el presupuesto ni los rendimientos: si una partida "
    "necesita más días hábiles de los que tiene programados, la marca como INCOHERENTE. Solo "
    "programa partidas que existen en el presupuesto. Solo SUB-DOC.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "revision": {"type": "string", "description": "por defecto 'A'"},
        },
        "required": ["proyecto"],
    },
)
async def generar_gantt(args: dict[str, Any]) -> dict[str, Any]:
    revision = args.get("revision") or "A"
    codigo_doc = "SOTICA-PLA-01"
    try:
        async with db.transaction() as conn:
            proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
            if proyecto is None:
                return _error(f"No existe la obra '{args['proyecto']}'.")
            base = await control.presupuesto_por_origen(conn, proyecto["id"], "base")
            if base is None:
                return _error("La obra no tiene presupuesto base de control: no hay qué programar.")
            partidas = await conn.fetch(
                """
                SELECT p.codigo_interno, p.descripcion, p.unidad, p.cantidad, p.capitulo,
                       p.apu_rendimiento, pl.fecha_inicio, pl.fecha_fin, pl.rendimiento_declarado
                  FROM partidas p LEFT JOIN planificacion_partida pl ON pl.partida_id = p.id
                 WHERE p.presupuesto_id = $1
                 ORDER BY pl.fecha_inicio NULLS LAST, p.capitulo, p.orden
                """,
                base["id"],
            )
            programadas = [p for p in partidas if p["fecha_inicio"]]
            if not programadas:
                return _error("Ninguna partida del presupuesto base tiene fechas de planificación.")

            wb = Workbook()
            wb.remove(wb.active)
            _hoja_portada(wb, proyecto, base, codigo_doc, revision,
                          proyecto["formatos_ratificados"],
                          titulo="Cronograma de obra", tipo_documento="Cronograma (Gantt)")

            ws = wb.create_sheet("Gantt")
            lunes = min(p["fecha_inicio"] for p in programadas)
            lunes -= dt.timedelta(days=lunes.weekday())
            ultimo = max(p["fecha_fin"] for p in programadas)
            semanas = [lunes + dt.timedelta(weeks=i)
                       for i in range((ultimo - lunes).days // 7 + 1)]
            fijas = ["Código", "Partida", "Unidad", "Cantidad", "Rendimiento (und/día)",
                     "Días hábiles requeridos", "Inicio", "Fin", "Días hábiles programados",
                     "Coherencia"]
            _encabezado(ws, fijas + [f"{s:%d/%m}" for s in semanas])
            _anchos(ws, [11, 42, 8, 11, 13, 13, 11, 11, 13, 34] + [6] * len(semanas))
            hoy = dt.date.today()
            incoherentes, sin_rendimiento = [], []
            for fila, p in enumerate(programadas, start=2):
                rend = _rendimiento_dia(p)
                r = str(fila)
                _celdas(ws, fila, [
                    p["codigo_interno"], p["descripcion"], p["unidad"], float(p["cantidad"]),
                    rend if rend else "—",
                    f"=IF(ISNUMBER(E{r}),ROUNDUP(D{r}/E{r},0),\"—\")",
                    p["fecha_inicio"], p["fecha_fin"],
                    f"=NETWORKDAYS(G{r},H{r})",
                    f"=IF(ISNUMBER(F{r}),IF(F{r}>I{r},\"INCOHERENTE: faltan \"&(F{r}-I{r})"
                    f"&\" días hábiles\",\"OK\"),\"Sin rendimiento declarado\")",
                ], {4: "#,##0.00", 5: "#,##0.00", 7: "DD/MM/YYYY", 8: "DD/MM/YYYY"})
                for j, s in enumerate(semanas, start=len(fijas) + 1):
                    c = ws.cell(row=fila, column=j)
                    c.border = _BORDE
                    if s <= p["fecha_fin"] and s + dt.timedelta(days=6) >= p["fecha_inicio"]:
                        c.fill = _FILL_ACENTO
                    if s <= hoy <= s + dt.timedelta(days=6):
                        c.border = Border(left=Side(style="medium", color="9C0006"),
                                          right=Side(style="medium", color="9C0006"))
                if rend is None:
                    sin_rendimiento.append(p["codigo_interno"])
                else:
                    requeridos = math.ceil(float(p["cantidad"]) / rend)
                    disponibles = _dias_habiles(p["fecha_inicio"], p["fecha_fin"])
                    if requeridos > disponibles:
                        incoherentes.append({
                            "partida": p["codigo_interno"], "dias_habiles_requeridos": requeridos,
                            "dias_habiles_programados": disponibles,
                            "rendimiento": f"{rend:g} {p['unidad']}/día",
                        })

            # Curva S: % planificado al cierre de cada semana, con la misma ponderación que el
            # control de obra (fn_pct_plan_obra); el real solo existe a la fecha de hoy.
            real_hoy = float(await conn.fetchval("SELECT fn_pct_fisico_obra($1)", proyecto["id"]))
            ws_s = wb.create_sheet("Curva S")
            _encabezado(ws_s, ["Semana (cierre)", "% planificado acumulado", "% real acumulado"])
            _anchos(ws_s, [16, 22, 18])
            for fila, s in enumerate(semanas, start=2):
                cierre = s + dt.timedelta(days=6)
                plan = await conn.fetchval("SELECT fn_pct_plan_obra($1, $2)", proyecto["id"], cierre)
                _celdas(ws_s, fila, [cierre, float(plan or 0),
                                     real_hoy if s <= hoy <= cierre else None],
                        {1: "DD/MM/YYYY", 2: "0.00", 3: "0.00"})
            grafico = LineChart()
            grafico.title, grafico.y_axis.title = "Curva S — avance físico", "%"
            grafico.height, grafico.width = 9, 16
            grafico.x_axis.delete = grafico.y_axis.delete = False  # openpyxl los oculta por defecto
            grafico.x_axis.number_format = "DD/MM"
            grafico.y_axis.scaling.min, grafico.y_axis.scaling.max = 0, 100
            grafico.add_data(Reference(ws_s, min_col=2, max_col=3, min_row=1,
                                       max_row=len(semanas) + 1), titles_from_data=True)
            grafico.set_categories(Reference(ws_s, min_col=1, min_row=2, max_row=len(semanas) + 1))
            grafico.series[1].marker.symbol = "circle"
            grafico.legend.position = "b"
            ws_s.add_chart(grafico, "E2")

            no_programadas = [p["codigo_interno"] for p in partidas if not p["fecha_inicio"]]
            _hoja_simple(
                wb, "Premisas", ["Partida", "Rendimiento declarado", "Origen del rendimiento"],
                [[p["codigo_interno"], p["rendimiento_declarado"] or "—",
                  "APU de la partida" if p["apu_rendimiento"] else
                  ("Planificación" if p["rendimiento_declarado"] else "No declarado")]
                 for p in programadas]
                + [["Jornada", "Lunes a viernes", "Premisa propuesta: los días hábiles se cuentan "
                                                  "con NETWORKDAYS, sin feriados. Ratificar con SOTICA."]],
                "",
            )
            _hoja_simple(
                wb, "Hitos", ["Hito", "Fecha", "Nota"],
                [["Inicio contractual", proyecto["fecha_inicio_contractual"] or "—", ""],
                 ["Fin contractual", proyecto["fecha_fin_contractual"] or "—", ""],
                 ["Fin programado", ultimo,
                  "Excede el plazo contractual." if proyecto["fecha_fin_contractual"]
                  and ultimo > proyecto["fecha_fin_contractual"] else ""]]
                + [[f"Sin programar: {c}", "—", "Está en el presupuesto pero no tiene fechas."]
                   for c in no_programadas],
                "",
            )
            archivo_id, url = await _guardar_entregable(
                conn, proyecto, wb, codigo_doc, revision,
                f"Cronograma de obra — {proyecto['nombre_obra']}",
            )
            return _ok({
                "archivo_id": str(archivo_id), "codigo_documento": codigo_doc,
                "revision": revision, "url_descarga": url,
                "hojas": [w.title for w in wb.worksheets],
                "partidas_programadas": len(programadas),
                "partidas_sin_programar": no_programadas,
                "inicio": lunes.isoformat(), "fin_programado": ultimo.isoformat(),
                "incoherencias_con_rendimientos": incoherentes,
                "partidas_sin_rendimiento": sin_rendimiento,
                "nota": "Días hábiles lunes a viernes (premisa propuesta, sin feriados).",
            })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


_SECCION = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "contenido": {"type": "string",
                      "description": "Párrafos separados por línea en blanco; viñetas con '- '; "
                                     "**negrita**."},
        "tabla": {"type": "object", "properties": {
            "cabeceras": {"type": "array", "items": {"type": "string"}},
            "filas": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        }, "required": ["cabeceras", "filas"]},
    },
    "required": ["titulo"],
}


@registro.herramienta(
    "generar_word",
    "Genera un documento Word (.docx) en formato SOTICA: portada SOTICA-DOC-01, control de "
    "revisiones SOTICA-DOC-02, estilos, A4, pie con código y página. Tú redactas el contenido; "
    "el sistema ordena las secciones según el formato y marca como PENDIENTE DE CONFIRMACIÓN "
    "las obligatorias que no traigas. Usa EXACTAMENTE estos títulos de sección por tipo: "
    + "; ".join(f"{t} ({v['codigo']}): {', '.join(v['secciones'])}"
                for t, v in oficina.TIPOS.items())
    + ". Solo SUB-DOC.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "tipo": {"type": "string", "enum": sorted(oficina.TIPOS)},
            "titulo": {"type": "string"},
            "secciones": {"type": "array", "items": _SECCION},
            "revision": {"type": "string", "description": "por defecto 'A'"},
        },
        "required": ["proyecto", "tipo", "titulo", "secciones"],
    },
)
async def generar_word(args: dict[str, Any]) -> dict[str, Any]:
    revision = args.get("revision") or "A"
    tipo = args["tipo"]
    if tipo not in oficina.TIPOS:
        return _error(f"Tipo '{tipo}' no existe. Usa uno de: {', '.join(sorted(oficina.TIPOS))}.")
    codigo_doc = oficina.TIPOS[tipo]["codigo"]
    try:
        async with db.transaction() as conn:
            proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
            if proyecto is None:
                return _error(f"No existe la obra '{args['proyecto']}'.")
            datos, faltantes = oficina.documento_word(
                tipo, dict(proyecto), args["titulo"], args.get("secciones") or [], revision,
                proyecto["formatos_ratificados"])
            archivo_id, url = await _registrar_entregable(
                conn, proyecto, datos, "docx", codigo_doc, revision, args["titulo"])
        return _ok({
            "archivo_id": str(archivo_id), "codigo_documento": codigo_doc, "revision": revision,
            "url_descarga": url, "secciones_pendientes": faltantes,
            "advertencias": ([f"Secciones obligatorias sin contenido, marcadas PENDIENTE: "
                              f"{', '.join(faltantes)}."] if faltantes else [])
                            + ([] if proyecto["formatos_ratificados"] else
                               ["Formato SOTICA propuesto — pendiente de ratificación."]),
        })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


@registro.herramienta(
    "generar_presentacion",
    "Genera una presentación PowerPoint (.pptx) en formato SOTICA (SOTICA-PRS-01, propuesto) "
    "para comités de licitación, juntas o inspecciones: portada SOTICA y una diapositiva por "
    "tema con título y viñetas cortas. Solo SUB-DOC.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "titulo": {"type": "string"},
            "diapositivas": {"type": "array", "items": {
                "type": "object",
                "properties": {"titulo": {"type": "string"},
                               "vinetas": {"type": "array", "items": {"type": "string"}}},
                "required": ["titulo", "vinetas"]}},
            "revision": {"type": "string", "description": "por defecto 'A'"},
        },
        "required": ["proyecto", "titulo", "diapositivas"],
    },
)
async def generar_presentacion(args: dict[str, Any]) -> dict[str, Any]:
    revision = args.get("revision") or "A"
    codigo_doc = "SOTICA-PRS-01"
    try:
        async with db.transaction() as conn:
            proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
            if proyecto is None:
                return _error(f"No existe la obra '{args['proyecto']}'.")
            datos = oficina.presentacion(dict(proyecto), args["titulo"], args["diapositivas"],
                                         codigo_doc, revision, proyecto["formatos_ratificados"])
            archivo_id, url = await _registrar_entregable(
                conn, proyecto, datos, "pptx", codigo_doc, revision, args["titulo"])
        return _ok({"archivo_id": str(archivo_id), "codigo_documento": codigo_doc,
                    "revision": revision, "url_descarga": url,
                    "diapositivas": len(args["diapositivas"]) + 1})
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


# El servidor MCP se construye en stdio_server.py a partir de este registro.
__all__ = ["registro"]
