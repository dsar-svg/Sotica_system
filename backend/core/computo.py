"""Persistencia de cómputos métricos (SUB-CM).

Escribe únicamente en un presupuesto en estado 'borrador'. Marcar cuál es la
base de control es una decisión humana, no del agente: se hace desde el panel
(`POST /api/proyectos/{id}/presupuestos/{pid}/marcar-base`).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from . import control


async def _borrador(conn: asyncpg.Connection, proyecto: asyncpg.Record) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT * FROM presupuestos WHERE proyecto_id = $1 AND estado = 'borrador' "
        "ORDER BY version DESC LIMIT 1",
        proyecto["id"],
    )
    if row is not None:
        return row
    version = await conn.fetchval(
        "SELECT COALESCE(max(version), 0) + 1 FROM presupuestos WHERE proyecto_id = $1",
        proyecto["id"],
    )
    return await conn.fetchrow(
        """
        INSERT INTO presupuestos (proyecto_id, version, tipo, estado, moneda, fecha_base,
                                  creado_por)
        VALUES ($1, $2, 'oferente', 'borrador', $3, $4, 'SUB-CM')
        RETURNING *
        """,
        proyecto["id"], version, proyecto["moneda_base"], proyecto["fecha_base_precios"],
    )


async def registrar_computo(
    conn: asyncpg.Connection,
    proyecto_ref: str,
    partidas: list[dict[str, Any]],
    no_computables: list[dict[str, Any]],
) -> dict[str, Any]:
    proyecto = await control.proyecto_por_ref(conn, proyecto_ref)
    if proyecto is None:
        raise ValueError(f"No existe la obra '{proyecto_ref}'.")

    presupuesto = await _borrador(conn, proyecto)
    if presupuesto["estado"] != "borrador":
        raise ValueError("Solo se computa sobre un presupuesto en borrador.")

    escritas: list[dict[str, Any]] = []
    for p in partidas:
        partida_id = await conn.fetchval(
            """
            INSERT INTO partidas
                (presupuesto_id, proyecto_id, codigo_covenin, codigo_interno, capitulo,
                 subcapitulo, descripcion, unidad, cantidad, especialidad,
                 etiqueta_cantidad, fuente_cantidad, agente_responsable, orden)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::etiqueta_dato,$12,'SUB-CM',
                    (SELECT COALESCE(max(orden),0)+1 FROM partidas WHERE presupuesto_id = $1))
            ON CONFLICT (presupuesto_id, codigo_interno) DO UPDATE SET
                descripcion = EXCLUDED.descripcion,
                unidad = EXCLUDED.unidad,
                cantidad = EXCLUDED.cantidad,
                etiqueta_cantidad = EXCLUDED.etiqueta_cantidad,
                fuente_cantidad = EXCLUDED.fuente_cantidad
            RETURNING id
            """,
            presupuesto["id"], proyecto["id"], p.get("codigo_covenin"), p["codigo_interno"],
            p["capitulo"], p.get("subcapitulo"), p["descripcion"], p["unidad"],
            float(p["cantidad"]), p.get("especialidad"),
            p["etiqueta_cantidad"], p["fuente_cantidad"],
        )
        # Las mediciones se reescriben completas: la hoja refleja el último cómputo.
        await conn.execute("DELETE FROM mediciones WHERE partida_id = $1", partida_id)
        for m in p.get("mediciones") or []:
            await conn.execute(
                """
                INSERT INTO mediciones (partida_id, referencia, expresion, subtotal, unidad,
                                        etiqueta, observacion, agente)
                VALUES ($1,$2,$3,$4,$5,$6::etiqueta_dato,$7,'SUB-CM')
                """,
                partida_id, m["referencia"], m["expresion"], float(m["subtotal"]),
                p["unidad"], m.get("etiqueta", p["etiqueta_cantidad"]), m.get("observacion"),
            )
        escritas.append({
            "codigo_interno": p["codigo_interno"],
            "cantidad": float(p["cantidad"]),
            "unidad": p["unidad"],
            "etiqueta": p["etiqueta_cantidad"],
            "mediciones": len(p.get("mediciones") or []),
        })

    for f in no_computables:
        await conn.execute(
            """
            INSERT INTO faltantes (proyecto_id, ambito, descripcion, impacto_estimado,
                                   como_obtenerlo, agente)
            VALUES ($1,$2,$3,$4,$5,'SUB-CM')
            """,
            proyecto["id"], f["ambito"], f["descripcion"],
            f.get("impacto_estimado"), f["como_obtenerlo"],
        )

    return {
        "presupuesto": {
            "id": str(presupuesto["id"]),
            "version": presupuesto["version"],
            "estado": presupuesto["estado"],
            "es_base_control": presupuesto["es_base_control"],
        },
        "partidas_escritas": escritas,
        "no_computables_registradas": len(no_computables),
        "nota": (
            "Escrito en el presupuesto BORRADOR. Marcar la base de control es decisión "
            "humana desde el panel; hasta entonces el seguimiento de obra no mide contra "
            "estas cantidades."
        ),
    }
