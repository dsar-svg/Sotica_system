"""Registro de avance y flujo de resolución de bloqueos.

Invariante estructural: nada de lo que hay aquí escribe en `presupuestos` ni en
`partidas`. El presupuesto base es inmutable para el control de obra; el avance
se cruza contra él.
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import asyncpg

from . import control


def _fecha(valor: Any, defecto: dt.date | None = None) -> dt.date:
    if valor in (None, ""):
        if defecto is None:
            raise ValueError("Falta la fecha.")
        return defecto
    if isinstance(valor, dt.date):
        return valor
    return dt.date.fromisoformat(str(valor)[:10])


async def _abrir_bloqueo(
    conn: asyncpg.Connection,
    proyecto_id: UUID,
    reporte_id: UUID | None,
    tipo: str,
    descripcion: str,
    item: dict[str, Any],
) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO bloqueos (proyecto_id, reporte_id, tipo, descripcion, datos, abierto_por)
        VALUES ($1, $2, $3::tipo_bloqueo, $4, $5::jsonb, 'SUB-AVA')
        RETURNING id
        """,
        proyecto_id, reporte_id, tipo, descripcion, item,
    )


async def _retener_avance(
    conn: asyncpg.Connection,
    bloqueo_id: UUID,
    proyecto_id: UUID,
    reporte_id: UUID,
    item: dict[str, Any],
) -> UUID:
    """El avance queda en cuarentena: etiquetado pendiente_confirmacion y FUERA
    del consolidado hasta que un humano resuelva el bloqueo. Cascada explícita."""
    return await conn.fetchval(
        """
        INSERT INTO avances_en_espera
            (bloqueo_id, proyecto_id, reporte_id, codigo_partida_reportado, fecha_avance,
             cantidad_periodo, unidad, metodo, etiqueta, confianza, observacion, evidencia_ids)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'pendiente_confirmacion',$9::nivel_confianza,$10,$11::uuid[])
        RETURNING id
        """,
        bloqueo_id, proyecto_id, reporte_id,
        item.get("codigo_partida", "(sin código)"),
        _fecha(item.get("fecha_avance")),
        float(item.get("cantidad_periodo") or 0),
        item.get("unidad", ""),
        item.get("metodo", "(no declarado)"),
        item.get("confianza", "bajo"),
        item.get("observacion"),
        [UUID(x) for x in (item.get("evidencia_archivo_ids") or [])],
    )


async def registrar_avance(
    conn: asyncpg.Connection,
    proyecto_ref: str,
    reporte_id: str,
    avances: list[dict[str, Any]],
    fecha_corte: str | None = None,
) -> dict[str, Any]:
    proyecto = await control.proyecto_por_ref(conn, proyecto_ref)
    if proyecto is None:
        raise ValueError(f"No existe la obra '{proyecto_ref}'.")
    base = await control.presupuesto_base(conn, proyecto["id"])
    if base is None:
        raise ValueError(
            "La obra no tiene un presupuesto marcado como base de control. "
            "Sin presupuesto base no hay contra qué medir el avance."
        )

    rep = await conn.fetchrow(
        "SELECT * FROM reportes_avance WHERE id = $1 AND proyecto_id = $2",
        UUID(reporte_id), proyecto["id"],
    )
    if rep is None:
        raise ValueError("El reporte crudo indicado no existe para esta obra.")

    corte = _fecha(fecha_corte, dt.date.today())
    registrados: list[dict[str, Any]] = []
    rechazos: list[dict[str, Any]] = []
    desviaciones: list[dict[str, Any]] = []
    partidas_tocadas: set[UUID] = set()

    for item in avances:
        codigo = str(item.get("codigo_partida", "")).strip()
        partida = await control.buscar_partida(conn, base["id"], codigo) if codigo else None

        # --- Bloqueo 1: la partida no existe en el presupuesto base ---------
        if partida is None:
            descripcion = (
                f"El reporte declara avance en '{codigo or '(sin código)'}', que no existe en el "
                f"presupuesto base {base['version']} de la obra. Puede ser obra extra, obra "
                "adicional o un error de atribución: son figuras distintas y la decisión es de "
                "ORQ-COST con el usuario. El avance queda retenido y NO entra al consolidado."
            )
            bloqueo_id = await _abrir_bloqueo(
                conn, proyecto["id"], rep["id"], "partida_no_presupuestada", descripcion, item
            )
            espera_id = await _retener_avance(conn, bloqueo_id, proyecto["id"], rep["id"], item)
            await control._abrir_desviacion(
                conn, proyecto["id"], None, None, "partida_no_presupuestada", "alta",
                None, float(item.get("cantidad_periodo") or 0), None, descripcion,
            )
            rechazos.append({
                "codigo_partida": codigo,
                "motivo": "partida_no_presupuestada",
                "bloqueo_id": str(bloqueo_id),
                "avance_en_espera_id": str(espera_id),
                "detalle": descripcion,
            })
            continue

        # --- Bloqueo 2: unidad distinta a la de la partida ------------------
        unidad = str(item.get("unidad", "")).strip()
        if unidad.lower() != str(partida["unidad"]).lower():
            descripcion = (
                f"{partida['codigo_interno']}: el reporte mide en '{unidad}' y la partida está "
                f"en '{partida['unidad']}'. No se convierte automáticamente. Requiere que el "
                "residente aclare la unidad o que el usuario confirme la conversión."
            )
            bloqueo_id = await _abrir_bloqueo(
                conn, proyecto["id"], rep["id"], "inconsistencia_unidad", descripcion, item
            )
            espera_id = await _retener_avance(conn, bloqueo_id, proyecto["id"], rep["id"], item)
            desviaciones.append(await control._abrir_desviacion(
                conn, proyecto["id"], partida["id"], None, "inconsistencia_unidad", "alta",
                None, None, None, descripcion,
            ))
            rechazos.append({
                "codigo_partida": codigo,
                "motivo": "inconsistencia_unidad",
                "bloqueo_id": str(bloqueo_id),
                "avance_en_espera_id": str(espera_id),
                "detalle": descripcion,
            })
            continue

        # --- Etiquetado: 'confirmado' exige evidencia ------------------------
        evidencia = [UUID(x) for x in (item.get("evidencia_archivo_ids") or [])]
        etiqueta = str(item.get("etiqueta", "inferido"))
        nota_etiqueta = None
        if etiqueta == "confirmado" and not evidencia:
            etiqueta = "inferido"
            nota_etiqueta = (
                "Se declaró 'confirmado' sin evidencia adjunta. Un avance sin valuación, acta "
                "o medición documentada no es confirmable: se registró como 'inferido'."
            )

        avance_id = await conn.fetchval(
            """
            INSERT INTO avances_partida
                (reporte_id, proyecto_id, partida_id, fecha_avance, cantidad_periodo, unidad,
                 metodo, etiqueta, confianza, observacion, interpretado_por)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::etiqueta_dato,$9::nivel_confianza,$10,'SUB-AVA')
            RETURNING id
            """,
            rep["id"], proyecto["id"], partida["id"],
            _fecha(item.get("fecha_avance"), rep["fecha_reporte"]),
            float(item["cantidad_periodo"]), unidad,
            item.get("metodo", "(no declarado)"), etiqueta,
            item.get("confianza", "bajo"), item.get("observacion"),
        )
        for archivo_id in evidencia:
            await conn.execute(
                "INSERT INTO avance_evidencia (avance_id, archivo_id) VALUES ($1,$2) "
                "ON CONFLICT DO NOTHING",
                avance_id, archivo_id,
            )

        if not evidencia:
            desviaciones.append(await control._abrir_desviacion(
                conn, proyecto["id"], partida["id"], avance_id, "sin_evidencia", "media",
                None, float(item["cantidad_periodo"]), None,
                f"{partida['codigo_interno']}: avance declarado sin foto, valuación ni medición "
                "adjunta. Se registra, pero la falta de evidencia queda visible.",
            ))

        partidas_tocadas.add(partida["id"])
        registrados.append({
            "avance_id": str(avance_id),
            "codigo_partida": partida["codigo_interno"],
            "descripcion": partida["descripcion"],
            "cantidad_periodo": float(item["cantidad_periodo"]),
            "unidad": unidad,
            "fecha_avance": _fecha(item.get("fecha_avance"), rep["fecha_reporte"]).isoformat(),
            "etiqueta": etiqueta,
            "confianza": item.get("confianza", "bajo"),
            "evidencia": len(evidencia),
            "nota": nota_etiqueta,
        })

    # Recálculo + evaluación de desviaciones: siempre, para cada partida tocada.
    for partida_id in partidas_tocadas:
        calculo = await control.recalcular_partida(conn, partida_id, corte)
        desviaciones += await control.evaluar_desviaciones_partida(
            conn, proyecto["id"], calculo, corte
        )

    await conn.execute(
        """
        UPDATE reportes_avance
           SET estado = $2::estado_reporte, procesado_en = now(), procesado_por = 'SUB-AVA',
               nota_procesamiento = $3
         WHERE id = $1
        """,
        rep["id"],
        "procesado" if registrados else "rechazado",
        f"{len(registrados)} avance(s) registrado(s), {len(rechazos)} retenido(s) por bloqueo.",
    )

    estado = await control.recalcular_obra(conn, proyecto["id"], corte)

    return {
        "avances_registrados": len(registrados),
        "detalle_registrados": registrados,
        "rechazos": rechazos,
        "desviaciones_detectadas": desviaciones,
        "estado_consolidado": estado,
    }


# ---------------------------------------------------------------------------
# Bloqueos
# ---------------------------------------------------------------------------

async def consultar_bloqueos(
    conn: asyncpg.Connection, proyecto_ref: str | None = None, incluir_resueltos: bool = False
) -> dict[str, Any]:
    proyecto_id = None
    if proyecto_ref:
        proyecto = await control.proyecto_por_ref(conn, proyecto_ref)
        if proyecto is None:
            raise ValueError(f"No existe la obra '{proyecto_ref}'.")
        proyecto_id = proyecto["id"]

    filas = await conn.fetch(
        """
        SELECT b.id, b.proyecto_id, p.codigo AS codigo_proyecto, p.nombre_obra,
               b.tipo, b.descripcion, b.datos, b.estado, b.abierto_por, b.abierto_en,
               (now()::date - b.abierto_en::date) AS dias_abierto,
               b.decision, b.resolucion, b.confirmacion_usuario,
               r.fecha_reporte, r.reportado_por,
               (SELECT count(*) FROM avances_en_espera e
                 WHERE e.bloqueo_id = b.id AND e.estado = 'en_espera') AS avances_retenidos
          FROM bloqueos b
          JOIN proyectos p ON p.id = b.proyecto_id
          LEFT JOIN reportes_avance r ON r.id = b.reporte_id
         WHERE ($1::uuid IS NULL OR b.proyecto_id = $1)
           AND ($2::boolean OR b.estado = 'abierto')
         ORDER BY b.estado, b.abierto_en
        """,
        proyecto_id, incluir_resueltos,
    )
    bloqueos = []
    for r in filas:
        d = dict(r)
        d["id"] = str(d["id"])
        d["proyecto_id"] = str(d["proyecto_id"])
        d["abierto_en"] = d["abierto_en"].isoformat()
        d["fecha_reporte"] = d["fecha_reporte"].isoformat() if d["fecha_reporte"] else None
        bloqueos.append(d)

    return {
        "bloqueos": bloqueos,
        "abiertos": sum(1 for b in bloqueos if b["estado"] == "abierto"),
        "nota": (
            "Un bloqueo solo lo resuelve ORQ-COST con confirmación explícita del usuario en el "
            "chat. Mientras siga abierto, los avances retenidos NO entran al estado consolidado."
        ),
    }


async def resolver_bloqueo(
    conn: asyncpg.Connection,
    bloqueo_id: str,
    decision: str,
    confirmacion_usuario: str,
    resolucion: str,
    codigo_partida_destino: str | None = None,
) -> dict[str, Any]:
    """Única vía de resolución. Exige la confirmación literal del usuario:
    sin ella, el bloqueo no se cierra. No hay resolución automática."""
    if not confirmacion_usuario or not confirmacion_usuario.strip():
        raise ValueError(
            "No se puede resolver un bloqueo sin la confirmación explícita del usuario. "
            "Pregunta en el chat y transcribe su respuesta."
        )

    bloqueo = await conn.fetchrow("SELECT * FROM bloqueos WHERE id = $1", UUID(bloqueo_id))
    if bloqueo is None:
        raise ValueError("El bloqueo indicado no existe.")
    if bloqueo["estado"] != "abierto":
        raise ValueError(f"El bloqueo ya está {bloqueo['estado']}.")

    proyecto_id = bloqueo["proyecto_id"]
    base = await control.presupuesto_base(conn, proyecto_id)
    retenidos = await conn.fetch(
        "SELECT * FROM avances_en_espera WHERE bloqueo_id = $1 AND estado = 'en_espera'",
        bloqueo["id"],
    )
    promovidos: list[dict[str, Any]] = []
    corte = dt.date.today()

    if decision == "mapear_a_partida":
        if not codigo_partida_destino:
            raise ValueError("mapear_a_partida requiere codigo_partida_destino.")
        partida = await control.buscar_partida(conn, base["id"], codigo_partida_destino)
        if partida is None:
            raise ValueError(
                f"'{codigo_partida_destino}' tampoco existe en el presupuesto base. "
                "Si el trabajo está realmente fuera del presupuesto, la decisión es "
                "diferir_a_obra_extra."
            )
        for e in retenidos:
            if str(e["unidad"]).lower() != str(partida["unidad"]).lower():
                raise ValueError(
                    f"El avance retenido está en '{e['unidad']}' y la partida destino en "
                    f"'{partida['unidad']}'. Aclarar la unidad antes de mapear."
                )
            avance_id = await conn.fetchval(
                """
                INSERT INTO avances_partida
                    (reporte_id, proyecto_id, partida_id, fecha_avance, cantidad_periodo, unidad,
                     metodo, etiqueta, confianza, observacion, interpretado_por)
                VALUES ($1,$2,$3,$4,$5,$6,$7,'inferido',$8::nivel_confianza,$9,'ORQ-COST')
                RETURNING id
                """,
                e["reporte_id"], proyecto_id, partida["id"], e["fecha_avance"],
                e["cantidad_periodo"], e["unidad"], e["metodo"], e["confianza"],
                (e["observacion"] or "")
                + f" | Promovido desde bloqueo {bloqueo['id']} por decisión del usuario.",
            )
            for archivo_id in (e["evidencia_ids"] or []):
                await conn.execute(
                    "INSERT INTO avance_evidencia (avance_id, archivo_id) VALUES ($1,$2) "
                    "ON CONFLICT DO NOTHING",
                    avance_id, archivo_id,
                )
            await conn.execute(
                "UPDATE avances_en_espera SET estado='promovido', promovido_a=$2 WHERE id=$1",
                e["id"], avance_id,
            )
            promovidos.append({"avance_id": str(avance_id), "partida": partida["codigo_interno"]})

        calculo = await control.recalcular_partida(conn, partida["id"], corte)
        await control.evaluar_desviaciones_partida(conn, proyecto_id, calculo, corte)

    elif decision == "diferir_a_obra_extra":
        # No se crea partida: el presupuesto base no se toca. Queda como faltante
        # declarado para que ORQ-COST lo trate como obra extra/adicional aparte.
        await conn.execute("UPDATE avances_en_espera SET estado='diferido' WHERE bloqueo_id=$1",
                           bloqueo["id"])
        await conn.execute(
            """
            INSERT INTO faltantes (proyecto_id, ambito, descripcion, impacto_estimado,
                                   como_obtenerlo, agente)
            VALUES ($1, 'control de obra', $2, $3, $4, 'ORQ-COST')
            """,
            proyecto_id,
            f"Trabajo ejecutado fuera del presupuesto base (bloqueo {bloqueo['id']}): "
            f"{bloqueo['descripcion']}",
            "Pendiente de valorar como obra extra o adicional.",
            "Decisión contractual del usuario + APU nuevo aprobado por ORQ-COST.",
        )

    elif decision == "descartar":
        await conn.execute("UPDATE avances_en_espera SET estado='descartado' WHERE bloqueo_id=$1",
                           bloqueo["id"])
    else:
        raise ValueError(
            "decision debe ser mapear_a_partida | diferir_a_obra_extra | descartar."
        )

    await conn.execute(
        """
        UPDATE bloqueos
           SET estado='resuelto', decision=$2::decision_bloqueo, resolucion=$3,
               confirmacion_usuario=$4, resuelto_por='ORQ-COST', resuelto_en=now()
         WHERE id = $1
        """,
        bloqueo["id"], decision, resolucion, confirmacion_usuario.strip(),
    )

    estado = await control.recalcular_obra(conn, proyecto_id, corte)
    return {
        "bloqueo_id": str(bloqueo["id"]),
        "decision": decision,
        "avances_promovidos": promovidos,
        "avances_retenidos_afectados": len(retenidos),
        "estado_consolidado": estado,
    }
