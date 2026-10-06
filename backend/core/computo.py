"""Persistencia de cómputos métricos (SUB-CM).

Escribe únicamente en un presupuesto en estado 'borrador'. Marcar cuál es la
base de control es una decisión humana, no del agente: se hace desde el panel
(`POST /api/proyectos/{id}/presupuestos/{pid}/marcar-base`).
"""
from __future__ import annotations

import ast
import operator
from typing import Any
from uuid import UUID

import asyncpg

from . import control

# De más firme a menos firme (PDF 3.5).
_FIRMEZA = ["confirmado", "referencial", "inferido", "pendiente_confirmacion"]

_OPERADORES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
               ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def evaluar_expresion(expresion: str) -> float:
    """Evalúa el despiece de una hoja de medición: números, + - * / y paréntesis.

    La aritmética la hace el sistema, no el modelo: acepta coma decimal y × o x como
    multiplicación (`45,00 x 2,80`), y rechaza cualquier otra cosa.
    """
    texto = expresion.replace(",", ".").replace("×", "*").replace("x", "*").replace("X", "*")

    def ev(nodo: ast.AST) -> float:
        if isinstance(nodo, ast.Expression):
            return ev(nodo.body)
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
            return float(nodo.value)
        if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OPERADORES:
            return _OPERADORES[type(nodo.op)](ev(nodo.left), ev(nodo.right))
        if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OPERADORES:
            return _OPERADORES[type(nodo.op)](ev(nodo.operand))
        raise ValueError

    try:
        return round(ev(ast.parse(texto, mode="eval")), 6)
    except (SyntaxError, ValueError, ZeroDivisionError):
        raise ValueError(
            f"La expresión '{expresion}' no es aritmética evaluable. Usa solo números, "
            "+ - * / y paréntesis, una operación por línea (ej. '45.00*2.80', '-6*(0.90*2.10)')."
        ) from None


def recalcular(partidas: list[dict[str, Any]]) -> list[str]:
    """Reemplaza subtotales y cantidades por los que salen de las expresiones.

    Devuelve las correcciones hechas, para que el agente informe el número correcto.
    Una partida sin mediciones conserva su cantidad (dato dado por el usuario).
    """
    correcciones: list[str] = []
    for p in partidas:
        mediciones = p.get("mediciones") or []
        for m in mediciones:
            calculado = round(evaluar_expresion(m["expresion"]), 4)
            if abs(calculado - float(m.get("subtotal") or 0)) > 0.005:
                correcciones.append(f"{p['codigo_interno']}: '{m['expresion']}' = {calculado:g}, "
                                    f"no {m.get('subtotal')}")
            m["subtotal"] = calculado
        if mediciones:
            total = round(sum(m["subtotal"] for m in mediciones), 2)
            if abs(total - float(p.get("cantidad") or 0)) > 0.005:
                correcciones.append(f"{p['codigo_interno']}: cantidad = {total:g} {p['unidad']} "
                                    f"(suma de la hoja de medición), no {p.get('cantidad')}")
            p["cantidad"] = total
    return correcciones


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

    correcciones = recalcular(partidas)
    presupuesto = await _borrador(conn, proyecto)
    if presupuesto["estado"] != "borrador":
        raise ValueError("Solo se computa sobre un presupuesto en borrador.")

    escritas: list[dict[str, Any]] = []
    for p in partidas:
        previa = await conn.fetchrow(
            "SELECT id, cantidad, unidad, etiqueta_cantidad, fuente_cantidad FROM partidas "
            "WHERE presupuesto_id = $1 AND codigo_interno = $2",
            presupuesto["id"], p["codigo_interno"],
        )
        modo = p.get("modo")
        if previa is not None:
            # Reescribir en silencio una partida ya computada perdería el cómputo anterior
            # (p. ej. planta baja al registrar planta alta con el mismo código).
            if modo not in ("agregar", "reemplazar"):
                refs = await conn.fetch(
                    "SELECT referencia, subtotal FROM mediciones WHERE partida_id = $1",
                    previa["id"])
                detalle = "; ".join(f"{r['referencia']} = {float(r['subtotal']):g}" for r in refs)
                raise ValueError(
                    f"La partida {p['codigo_interno']} ya está en el borrador con "
                    f"{float(previa['cantidad']):g} {previa['unidad']}"
                    + (f" ({detalle})" if detalle else "")
                    + ". Indica modo='agregar' si este cómputo es de otro sector o planta y se "
                      "suma, o modo='reemplazar' si corrige el anterior. No se escribió nada."
                )
            if modo == "agregar" and previa["unidad"] != p["unidad"]:
                raise ValueError(
                    f"No se mezclan unidades: {p['codigo_interno']} está en {previa['unidad']} "
                    f"y el cómputo nuevo viene en {p['unidad']}."
                )
        sumar = previa is not None and modo == "agregar"
        etiqueta = p["etiqueta_cantidad"]
        fuente = p["fuente_cantidad"]
        if sumar:
            # La partida queda con la etiqueta menos firme de sus partes.
            etiqueta = max(etiqueta, previa["etiqueta_cantidad"], key=_FIRMEZA.index)
            fuente = f"{previa['fuente_cantidad']}; {fuente}"
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
            float(p["cantidad"]) + (float(previa["cantidad"]) if sumar else 0),
            p.get("especialidad"), etiqueta, fuente,
        )
        if not sumar:
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
        # Con hoja de medición, la cantidad es la suma de toda la hoja (vieja + nueva al agregar).
        cantidad = await conn.fetchval(
            """
            UPDATE partidas SET cantidad = COALESCE(
                (SELECT round(sum(subtotal), 2) FROM mediciones WHERE partida_id = $1), cantidad)
             WHERE id = $1 RETURNING cantidad
            """,
            partida_id,
        )
        n_med = await conn.fetchval("SELECT count(*) FROM mediciones WHERE partida_id = $1",
                                    partida_id)
        escritas.append({
            "codigo_interno": p["codigo_interno"],
            "cantidad": float(cantidad),
            "unidad": p["unidad"],
            "etiqueta": etiqueta,
            "mediciones": n_med,
            "modo": "agregado al cómputo anterior" if sumar else
                    ("reemplazó el cómputo anterior" if previa is not None else "nueva"),
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
        "correcciones_aritmeticas": correcciones or None,
        "no_computables_registradas": len(no_computables),
        "nota": (
            "Escrito en el presupuesto BORRADOR. Marcar la base de control es decisión "
            "humana desde el panel; hasta entonces el seguimiento de obra no mide contra "
            "estas cantidades."
        ),
    }
