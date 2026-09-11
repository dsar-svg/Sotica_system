"""Servidor MCP `sotica_obra` — presupuesto, avance y bloqueos.

MCP es la capa de herramientas: aquí no hay criterio de ingeniería, solo
lectura, escritura y aritmética. El criterio vive en los prompts de los agentes.

Se publica como servidor MCP stdio real (ver `backend/mcp/stdio_server.py`), así
que estas herramientas sirven a cualquier runtime que hable MCP. Los cuerpos de
las funciones y los JSON Schema son los mismos desde el ciclo 1.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..core import avance as avance_mod
from ..core import computo, control, db
from .registry import Registro, error as _error, ok as _ok

registro = Registro("sotica_obra")


# ---------------------------------------------------------------------------

@registro.herramienta(
    "consultar_presupuesto",
    "Devuelve el presupuesto base de una obra con sus partidas, unidades, cantidades, "
    "precios, etiquetas de dato y fuentes. Lectura pura: es contra esto que se mide "
    "cualquier avance y sobre esto que se computa cualquier cantidad.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string", "description": "uuid o código de obra (SOT-2026-014)"},
            "capitulo": {"type": "string", "description": "filtro opcional por capítulo"},
        },
        "required": ["proyecto"],
    },
)
async def consultar_presupuesto(args: dict[str, Any]) -> dict[str, Any]:
    async with db.acquire() as conn:
        proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
        if proyecto is None:
            return _error(f"No existe la obra '{args['proyecto']}'.")
        base = await control.presupuesto_base(conn, proyecto["id"])
        if base is None:
            return _error(
                "La obra no tiene presupuesto marcado como base de control (es_base_control)."
            )
        partidas = await conn.fetch(
            """
            SELECT codigo_interno, codigo_covenin, capitulo, subcapitulo, descripcion, unidad,
                   cantidad, precio_unitario, monto, especialidad,
                   etiqueta_cantidad, fuente_cantidad, etiqueta_precio, fuente_precio,
                   agente_responsable
              FROM partidas
             WHERE presupuesto_id = $1
               AND ($2::text IS NULL OR capitulo ILIKE $2)
             ORDER BY orden, codigo_interno
            """,
            base["id"], args.get("capitulo"),
        )
        return _ok({
            "proyecto": {
                "codigo": proyecto["codigo"],
                "nombre_obra": proyecto["nombre_obra"],
                "tipo_obra": proyecto["tipo_obra"],
                "moneda": proyecto["moneda_base"],
                "fecha_base_precios": proyecto["fecha_base_precios"],
                "norma_rectora": proyecto["norma_rectora"],
            },
            "presupuesto": {
                "version": base["version"], "tipo": base["tipo"], "estado": base["estado"],
                "moneda": base["moneda"], "fecha_base": base["fecha_base"],
                "clase_estimado": base["clase_estimado"],
            },
            "partidas": [dict(p) for p in partidas],
            "monto_total": float(sum(float(p["monto"] or 0) for p in partidas)),
        })


@registro.herramienta(
    "leer_reporte_avance",
    "Devuelve el reporte crudo de campo (texto libre, adjuntos, quién y cuándo) para que "
    "SUB-AVA lo interprete. Solo SUB-AVA debe usarla: ORQ-COST no lee crudos.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "reporte_id": {"type": "string", "description": "omitir para traer los pendientes"},
        },
        "required": ["proyecto"],
    },
)
async def leer_reporte_avance(args: dict[str, Any]) -> dict[str, Any]:
    async with db.acquire() as conn:
        proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
        if proyecto is None:
            return _error(f"No existe la obra '{args['proyecto']}'.")
        filas = await conn.fetch(
            """
            SELECT r.id, r.fecha_reporte, r.recibido_en, r.reportado_por, r.canal,
                   r.texto_libre, r.estado, r.anula_reporte_id,
                   COALESCE(json_agg(json_build_object(
                       'archivo_id', a.id, 'nombre', a.nombre, 'tipo', a.tipo,
                       'rol', ra.rol, 'capturado_en', a.capturado_en
                   )) FILTER (WHERE a.id IS NOT NULL), '[]') AS adjuntos
              FROM reportes_avance r
              LEFT JOIN reporte_adjuntos ra ON ra.reporte_id = r.id
              LEFT JOIN archivos a ON a.id = ra.archivo_id
             WHERE r.proyecto_id = $1
               AND ($2::uuid IS NULL OR r.id = $2::uuid)
               AND ($2::uuid IS NOT NULL OR r.estado = 'pendiente')
             GROUP BY r.id
             ORDER BY r.fecha_reporte DESC
            """,
            proyecto["id"], args.get("reporte_id"),
        )
        return _ok({
            "obra": proyecto["codigo"],
            "reportes": [dict(f) for f in filas],
            "nota": "Contenido sin interpretar, tal como lo cargó el residente/inspector.",
        })


@registro.herramienta(
    "registrar_avance",
    "Registra la interpretación estructurada de un reporte de campo, recalcula el estado "
    "consolidado y evalúa desviaciones, todo en una transacción. No toca el presupuesto base. "
    "Un avance cuya partida no existe, o cuya unidad no coincide, NO se registra: abre un "
    "bloqueo y el avance queda retenido fuera del consolidado. Solo SUB-AVA.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "reporte_id": {"type": "string", "description": "reporte crudo que se interpreta"},
            "fecha_corte": {"type": "string", "description": "YYYY-MM-DD; por defecto hoy"},
            "avances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "codigo_partida": {"type": "string"},
                        "fecha_avance": {"type": "string",
                                         "description": "fecha del evento en obra, no la de subida"},
                        "cantidad_periodo": {"type": "number"},
                        "unidad": {"type": "string",
                                   "description": "debe coincidir con la unidad de la partida"},
                        "metodo": {"type": "string",
                                   "description": "cómo se determinó la cantidad"},
                        "etiqueta": {"type": "string",
                                     "enum": ["confirmado", "inferido", "referencial",
                                              "pendiente_confirmacion"]},
                        "confianza": {"type": "string", "enum": ["alto", "medio", "bajo"]},
                        "evidencia_archivo_ids": {"type": "array", "items": {"type": "string"}},
                        "observacion": {"type": "string"},
                    },
                    "required": ["codigo_partida", "fecha_avance", "cantidad_periodo",
                                 "unidad", "metodo", "etiqueta", "confianza"],
                },
            },
        },
        "required": ["proyecto", "reporte_id", "avances"],
    },
)
async def registrar_avance(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with db.transaction() as conn:
            return _ok(await avance_mod.registrar_avance(
                conn, args["proyecto"], args["reporte_id"],
                args.get("avances") or [], args.get("fecha_corte"),
            ))
    except Exception as exc:  # noqa: BLE001 — el agente debe ver el motivo exacto
        return _error(str(exc))


@registro.herramienta(
    "consultar_estado_obra",
    "Estado consolidado de la obra: avance físico real vs. planificado, avance financiero, "
    "desviaciones abiertas y, SIEMPRE, la última fecha de avance y los días sin reporte. "
    "Única fuente para responder '¿cómo va la obra?'. No expone reportes crudos.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "codigo_partida": {"type": "string"},
            "capitulo": {"type": "string"},
            "fecha_corte": {"type": "string"},
            "incluir_desviaciones": {"type": "boolean"},
        },
        "required": ["proyecto"],
    },
)
async def consultar_estado_obra(args: dict[str, Any]) -> dict[str, Any]:
    async with db.acquire() as conn:
        proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
        if proyecto is None:
            return _error(f"No existe la obra '{args['proyecto']}'.")
        corte = (dt.date.fromisoformat(args["fecha_corte"])
                 if args.get("fecha_corte") else dt.date.today())
        return _ok(await control.estado_obra(
            conn, proyecto["id"],
            codigo_partida=args.get("codigo_partida"),
            capitulo=args.get("capitulo"),
            fecha_corte=corte,
            incluir_desviaciones=args.get("incluir_desviaciones", True),
        ))


@registro.herramienta(
    "consultar_bloqueos",
    "Bandeja de bloqueos abiertos por obra: lo que el sistema no resolvió solo y espera "
    "decisión humana, con los avances retenidos que cada uno mantiene fuera del consolidado.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string", "description": "omitir para ver todas las obras"},
            "incluir_resueltos": {"type": "boolean"},
        },
    },
)
async def consultar_bloqueos(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with db.acquire() as conn:
            return _ok(await avance_mod.consultar_bloqueos(
                conn, args.get("proyecto"), args.get("incluir_resueltos", False)
            ))
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


@registro.herramienta(
    "resolver_bloqueo",
    "Cierra un bloqueo con una decisión explícita del usuario. Solo ORQ-COST. Exige "
    "`confirmacion_usuario` con la respuesta literal del usuario en el chat: sin ella la "
    "herramienta rechaza la resolución. Decisiones: mapear_a_partida (era una partida "
    "existente mal nombrada), diferir_a_obra_extra (queda declarado como faltante; NO crea "
    "partida ni toca el presupuesto base), descartar (el reporte no procede).",
    {
        "type": "object",
        "properties": {
            "bloqueo_id": {"type": "string"},
            "decision": {"type": "string",
                         "enum": ["mapear_a_partida", "diferir_a_obra_extra", "descartar"]},
            "confirmacion_usuario": {
                "type": "string",
                "description": "transcripción literal de lo que el usuario confirmó en el chat",
            },
            "resolucion": {"type": "string", "description": "qué se decidió y por qué"},
            "codigo_partida_destino": {"type": "string",
                                       "description": "requerido si decision=mapear_a_partida"},
        },
        "required": ["bloqueo_id", "decision", "confirmacion_usuario", "resolucion"],
    },
)
async def resolver_bloqueo(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with db.transaction() as conn:
            return _ok(await avance_mod.resolver_bloqueo(
                conn, args["bloqueo_id"], args["decision"],
                args["confirmacion_usuario"], args["resolucion"],
                args.get("codigo_partida_destino"),
            ))
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


@registro.herramienta(
    "registrar_computo",
    "Persiste cómputos métricos: partidas y sus hojas de medición, con etiqueta de dato y "
    "referencia de plano obligatorias. Escribe SOLO en un presupuesto en estado 'borrador' "
    "(lo crea si no existe); nunca en uno aprobado ni en la base de control. Solo SUB-CM.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string"},
            "partidas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "codigo_interno": {"type": "string"},
                        "codigo_covenin": {"type": "string"},
                        "capitulo": {"type": "string"},
                        "descripcion": {"type": "string"},
                        "unidad": {"type": "string"},
                        "cantidad": {"type": "number"},
                        "especialidad": {"type": "string"},
                        "etiqueta_cantidad": {
                            "type": "string",
                            "enum": ["confirmado", "inferido", "referencial",
                                     "pendiente_confirmacion"],
                        },
                        "fuente_cantidad": {
                            "type": "string",
                            "description": "plano, corte, eje y cota que sustentan la cantidad",
                        },
                        "mediciones": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "referencia": {"type": "string"},
                                    "expresion": {"type": "string"},
                                    "subtotal": {"type": "number"},
                                    "etiqueta": {"type": "string"},
                                    "observacion": {"type": "string"},
                                },
                                "required": ["referencia", "expresion", "subtotal", "etiqueta"],
                            },
                        },
                    },
                    "required": ["codigo_interno", "capitulo", "descripcion", "unidad",
                                 "cantidad", "etiqueta_cantidad", "fuente_cantidad"],
                },
            },
            "no_computables": {
                "type": "array",
                "description": "cantidades que no se pudieron computar por falta de detalle",
                "items": {
                    "type": "object",
                    "properties": {
                        "ambito": {"type": "string"},
                        "descripcion": {"type": "string"},
                        "impacto_estimado": {"type": "string"},
                        "como_obtenerlo": {"type": "string"},
                    },
                    "required": ["ambito", "descripcion", "como_obtenerlo"],
                },
            },
        },
        "required": ["proyecto", "partidas"],
    },
)
async def registrar_computo(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with db.transaction() as conn:
            return _ok(await computo.registrar_computo(
                conn, args["proyecto"], args.get("partidas") or [],
                args.get("no_computables") or [],
            ))
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


# El servidor MCP se construye en stdio_server.py a partir de este registro.
__all__ = ["registro"]
