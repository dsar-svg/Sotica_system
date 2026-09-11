"""Lógica determinística de control de obra.

Todo lo que aquí se calcula es aritmética, no criterio: el agente interpreta el
reporte de campo, esta capa lo cruza contra el presupuesto base y saca las
cuentas siempre igual. Ningún porcentaje se pondera fuera de las funciones SQL
fn_pct_fisico_obra / fn_pct_plan_obra (ver db/schema.sql §9).
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import asyncpg

# Mayor rango = mayor incertidumbre. La calidad del acumulado es la PEOR de sus partes.
_RANGO_ETIQUETA = {
    "confirmado": 0,
    "inferido": 1,
    "referencial": 2,
    "pendiente_confirmacion": 3,
}
_ETIQUETA_POR_RANGO = {v: k for k, v in _RANGO_ETIQUETA.items()}


# ---------------------------------------------------------------------------
# Lecturas base
# ---------------------------------------------------------------------------

async def proyecto_por_ref(conn: asyncpg.Connection, ref: str) -> asyncpg.Record | None:
    """Acepta el uuid o el código de obra (SOT-2026-014)."""
    try:
        return await conn.fetchrow("SELECT * FROM proyectos WHERE id = $1", UUID(ref))
    except (ValueError, AttributeError):
        return await conn.fetchrow("SELECT * FROM proyectos WHERE codigo = $1", ref)


async def presupuesto_base(conn: asyncpg.Connection, proyecto_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM presupuestos WHERE proyecto_id = $1 AND es_base_control", proyecto_id
    )


async def config_vigente(conn: asyncpg.Connection, proyecto_id: UUID) -> dict[str, Any]:
    row = await conn.fetchrow("SELECT (fn_config_control($1)).*", proyecto_id)
    return dict(row) if row else {}


async def buscar_partida(
    conn: asyncpg.Connection, presupuesto_id: UUID, codigo: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT * FROM partidas
         WHERE presupuesto_id = $1
           AND (upper(codigo_interno) = upper($2) OR upper(codigo_covenin) = upper($2))
        """,
        presupuesto_id,
        codigo,
    )


# ---------------------------------------------------------------------------
# Recálculo del consolidado
# ---------------------------------------------------------------------------

async def recalcular_partida(
    conn: asyncpg.Connection, partida_id: UUID, fecha_corte: dt.date
) -> dict[str, Any]:
    partida = await conn.fetchrow("SELECT * FROM partidas WHERE id = $1", partida_id)
    agg = await conn.fetchrow(
        """
        SELECT COALESCE(sum(a.cantidad_periodo), 0)          AS acumulado,
               max(a.fecha_avance)                            AS ultima_fecha,
               count(*)                                       AS n_avances,
               bool_or(ev.avance_id IS NOT NULL)              AS tiene_evidencia,
               array_agg(DISTINCT a.etiqueta::text)           AS etiquetas
          FROM avances_partida a
          LEFT JOIN avance_evidencia ev ON ev.avance_id = a.id
         WHERE a.partida_id = $1
        """,
        partida_id,
    )

    acumulado = agg["acumulado"] or 0
    cantidad = partida["cantidad"] or 0
    pct_real = round(100.0 * float(acumulado) / float(cantidad), 2) if cantidad else 0.0
    pct_plan = await conn.fetchval("SELECT fn_pct_plan_partida($1, $2)", partida_id, fecha_corte)
    desviacion = round(pct_real - float(pct_plan), 2) if pct_plan is not None else None

    etiquetas = [e for e in (agg["etiquetas"] or []) if e]
    calidad = (
        _ETIQUETA_POR_RANGO[max(_RANGO_ETIQUETA[e] for e in etiquetas)] if etiquetas else None
    )

    precio = float(partida["precio_unitario"] or 0)
    ultimo_avance = await conn.fetchval(
        "SELECT id FROM avances_partida WHERE partida_id = $1 ORDER BY fecha_avance DESC, creado_en DESC LIMIT 1",
        partida_id,
    )

    await conn.execute(
        """
        INSERT INTO estado_obra_partida
            (partida_id, proyecto_id, cantidad_acumulada, cantidad_presupuestada,
             pct_fisico_real, pct_fisico_plan, desviacion_pp, monto_ejecutado,
             ultima_fecha_avance, ultimo_avance_id, calidad_dato, tiene_evidencia, actualizado_en)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
        ON CONFLICT (partida_id) DO UPDATE SET
            cantidad_acumulada = EXCLUDED.cantidad_acumulada,
            cantidad_presupuestada = EXCLUDED.cantidad_presupuestada,
            pct_fisico_real = EXCLUDED.pct_fisico_real,
            pct_fisico_plan = EXCLUDED.pct_fisico_plan,
            desviacion_pp = EXCLUDED.desviacion_pp,
            monto_ejecutado = EXCLUDED.monto_ejecutado,
            ultima_fecha_avance = EXCLUDED.ultima_fecha_avance,
            ultimo_avance_id = EXCLUDED.ultimo_avance_id,
            calidad_dato = EXCLUDED.calidad_dato,
            tiene_evidencia = EXCLUDED.tiene_evidencia,
            actualizado_en = now()
        """,
        partida_id,
        partida["proyecto_id"],
        acumulado,
        cantidad,
        pct_real,
        pct_plan,
        desviacion,
        round(float(acumulado) * precio, 2),
        agg["ultima_fecha"],
        ultimo_avance,
        calidad,
        bool(agg["tiene_evidencia"]),
    )

    return {
        "partida": partida,
        "acumulado": float(acumulado),
        "pct_real": pct_real,
        "pct_plan": float(pct_plan) if pct_plan is not None else None,
        "desviacion_pp": desviacion,
    }


async def _cerrar_desviaciones(
    conn: asyncpg.Connection, partida_id: UUID, tipos: tuple[str, ...], nota: str
) -> None:
    await conn.execute(
        """
        UPDATE desviaciones
           SET estado = 'cerrada', cerrada_en = now(), nota_cierre = $3
         WHERE partida_id = $1 AND estado = 'abierta' AND tipo::text = ANY($2::text[])
        """,
        partida_id,
        list(tipos),
        nota,
    )


async def evaluar_desviaciones_partida(
    conn: asyncpg.Connection,
    proyecto_id: UUID,
    calculo: dict[str, Any],
    fecha_corte: dt.date,
    avance_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Compara real vs. plan y abre las desviaciones que correspondan.
    Se ejecuta SIEMPRE que hay recálculo: no hay ruta que salte la evaluación."""
    partida = calculo["partida"]
    abiertas: list[dict[str, Any]] = []

    # 1. Atraso / adelanto contra el plan a la fecha.
    if calculo["desviacion_pp"] is not None:
        brecha = calculo["desviacion_pp"]
        severidad = await conn.fetchval(
            "SELECT fn_severidad_desviacion($1, $2)", proyecto_id, brecha
        )
        await _cerrar_desviaciones(
            conn, partida["id"], ("atraso", "adelanto"), "Superada por recálculo de avance."
        )
        if severidad != "informativa":
            tipo = "atraso" if brecha < 0 else "adelanto"
            descripcion = (
                f"{partida['codigo_interno']} — {partida['descripcion']}: "
                f"{calculo['pct_real']:.2f} % real vs. {calculo['pct_plan']:.2f} % planificado "
                f"al {fecha_corte:%d/%m/%Y} ({brecha:+.2f} pp)."
            )
            if tipo == "adelanto":
                descripcion += (
                    " Un adelanto sobre el plan también se reporta: puede indicar doble conteo, "
                    "error de medición o mal secuenciado."
                )
            abiertas.append(
                await _abrir_desviacion(
                    conn, proyecto_id, partida["id"], avance_id, tipo, severidad,
                    calculo["pct_plan"], calculo["pct_real"], brecha, descripcion,
                )
            )

    # 2. Sobre-ejecución respecto de la cantidad presupuestada.
    await _cerrar_desviaciones(
        conn, partida["id"], ("sobre_ejecucion",), "Superada por recálculo de avance."
    )
    if calculo["acumulado"] > float(partida["cantidad"]):
        exceso = calculo["acumulado"] - float(partida["cantidad"])
        abiertas.append(
            await _abrir_desviacion(
                conn, proyecto_id, partida["id"], avance_id, "sobre_ejecucion", "alta",
                float(partida["cantidad"]), calculo["acumulado"], exceso,
                f"{partida['codigo_interno']}: acumulado {calculo['acumulado']:.2f} "
                f"{partida['unidad']} excede la cantidad presupuestada "
                f"({float(partida['cantidad']):.2f} {partida['unidad']}) en {exceso:.2f}. "
                "Puede ser obra extra o error de cómputo — requiere decisión de ORQ-COST "
                "con el usuario; no se resuelve automáticamente.",
            )
        )
    return abiertas


async def _abrir_desviacion(
    conn: asyncpg.Connection,
    proyecto_id: UUID,
    partida_id: UUID | None,
    avance_id: UUID | None,
    tipo: str,
    severidad: str,
    valor_plan: float | None,
    valor_real: float | None,
    brecha: float | None,
    descripcion: str,
    impacto: str | None = None,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        INSERT INTO desviaciones
            (proyecto_id, partida_id, avance_id, tipo, severidad,
             valor_plan, valor_real, brecha, descripcion, impacto_estimado)
        VALUES ($1,$2,$3,$4::tipo_desviacion,$5::severidad,$6,$7,$8,$9,$10)
        RETURNING id, tipo, severidad, valor_plan, valor_real, brecha, descripcion, impacto_estimado
        """,
        proyecto_id, partida_id, avance_id, tipo, severidad,
        valor_plan, valor_real, brecha, descripcion, impacto,
    )
    return dict(row)


async def recalcular_obra(
    conn: asyncpg.Connection, proyecto_id: UUID, fecha_corte: dt.date
) -> dict[str, Any]:
    base = await presupuesto_base(conn, proyecto_id)
    if base is None:
        raise ValueError("La obra no tiene presupuesto marcado como base de control.")

    cfg = await config_vigente(conn, proyecto_id)

    pct_real = await conn.fetchval("SELECT fn_pct_fisico_obra($1)", proyecto_id)
    pct_plan = await conn.fetchval("SELECT fn_pct_plan_obra($1, $2)", proyecto_id, fecha_corte)

    tot = await conn.fetchrow(
        """
        SELECT COALESCE(sum(p.monto), 0)                                  AS presupuestado,
               COALESCE(sum(eop.monto_ejecutado), 0)                      AS ejecutado,
               count(*) FILTER (WHERE eop.ultima_fecha_avance IS NULL)    AS sin_avance
          FROM partidas p
          LEFT JOIN estado_obra_partida eop ON eop.partida_id = p.id
         WHERE p.presupuesto_id = $1
        """,
        base["id"],
    )
    ultima = await conn.fetchval(
        "SELECT max(fecha_avance) FROM avances_partida WHERE proyecto_id = $1", proyecto_id
    )
    dias_sin_reporte = (fecha_corte - ultima).days if ultima else None

    presupuestado = float(tot["presupuestado"] or 0)
    ejecutado = float(tot["ejecutado"] or 0)
    pct_fin = round(100.0 * ejecutado / presupuestado, 2) if presupuestado else 0.0

    # Desviación de obra por falta de reportes: la ausencia de información es un hallazgo.
    await conn.execute(
        """
        UPDATE desviaciones SET estado='cerrada', cerrada_en=now(),
               nota_cierre='Superada por recálculo.'
         WHERE proyecto_id=$1 AND partida_id IS NULL AND tipo='sin_reporte' AND estado='abierta'
        """,
        proyecto_id,
    )
    if dias_sin_reporte is None:
        await _abrir_desviacion(
            conn, proyecto_id, None, None, "sin_reporte", "alta", None, None, None,
            "No hay ningún avance cargado para esta obra. No es posible informar estado real.",
        )
    elif dias_sin_reporte >= int(cfg.get("dias_sin_reporte_alerta", 15)):
        await _abrir_desviacion(
            conn, proyecto_id, None, None, "sin_reporte", "media", None, None, dias_sin_reporte,
            f"Último avance registrado el {ultima:%d/%m/%Y} — hace {dias_sin_reporte} días. "
            f"Supera el umbral configurado de {cfg.get('dias_sin_reporte_alerta')} días.",
        )

    n_desv = await conn.fetchval(
        "SELECT count(*) FROM desviaciones WHERE proyecto_id=$1 AND estado='abierta'", proyecto_id
    )
    n_bloq = await conn.fetchval(
        "SELECT count(*) FROM bloqueos WHERE proyecto_id=$1 AND estado='abierto'", proyecto_id
    )
    n_espera = await conn.fetchval(
        "SELECT count(*) FROM avances_en_espera WHERE proyecto_id=$1 AND estado='en_espera'",
        proyecto_id,
    )

    await conn.execute(
        """
        INSERT INTO estado_obra
            (proyecto_id, presupuesto_base_id, pct_fisico_real, pct_fisico_plan, pct_financiero,
             monto_ejecutado, monto_presupuestado, ultima_fecha_avance, dias_sin_reporte,
             partidas_sin_avance, desviaciones_abiertas, bloqueos_abiertos, avances_en_espera,
             base_ponderacion_usada, config_ratificada, fecha_corte, actualizado_en)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::base_ponderacion,$15,$16, now())
        ON CONFLICT (proyecto_id) DO UPDATE SET
            presupuesto_base_id = EXCLUDED.presupuesto_base_id,
            pct_fisico_real = EXCLUDED.pct_fisico_real,
            pct_fisico_plan = EXCLUDED.pct_fisico_plan,
            pct_financiero = EXCLUDED.pct_financiero,
            monto_ejecutado = EXCLUDED.monto_ejecutado,
            monto_presupuestado = EXCLUDED.monto_presupuestado,
            ultima_fecha_avance = EXCLUDED.ultima_fecha_avance,
            dias_sin_reporte = EXCLUDED.dias_sin_reporte,
            partidas_sin_avance = EXCLUDED.partidas_sin_avance,
            desviaciones_abiertas = EXCLUDED.desviaciones_abiertas,
            bloqueos_abiertos = EXCLUDED.bloqueos_abiertos,
            avances_en_espera = EXCLUDED.avances_en_espera,
            base_ponderacion_usada = EXCLUDED.base_ponderacion_usada,
            config_ratificada = EXCLUDED.config_ratificada,
            fecha_corte = EXCLUDED.fecha_corte,
            actualizado_en = now()
        """,
        proyecto_id, base["id"], float(pct_real or 0),
        float(pct_plan) if pct_plan is not None else None, pct_fin,
        ejecutado, presupuestado, ultima, dias_sin_reporte,
        int(tot["sin_avance"] or 0), int(n_desv), int(n_bloq), int(n_espera),
        cfg.get("base_ponderacion", "monto"), bool(cfg.get("ratificado_por_sotica", False)),
        fecha_corte,
    )
    return await estado_obra(conn, proyecto_id, fecha_corte=fecha_corte)


# ---------------------------------------------------------------------------
# Estado consolidado (lectura)
# ---------------------------------------------------------------------------

def _advertencia_datos(ultima: dt.date | None, dias: int | None) -> str:
    """La regla del dato viejo. Sale SIEMPRE, la pidan o no."""
    if ultima is None:
        return (
            "No hay avances cargados para esta obra. No es posible informar estado real. "
            "No asumir que la obra sigue el cronograma planeado."
        )
    return (
        f"Último avance registrado el {ultima:%d/%m/%Y}"
        + (f" (hace {dias} días)." if dias is not None else ".")
        + " El avance mostrado NO está proyectado al día de hoy: no hay información posterior "
        "a esa fecha."
    )


async def estado_obra(
    conn: asyncpg.Connection,
    proyecto_id: UUID,
    codigo_partida: str | None = None,
    capitulo: str | None = None,
    fecha_corte: dt.date | None = None,
    incluir_desviaciones: bool = True,
) -> dict[str, Any]:
    proyecto = await conn.fetchrow("SELECT * FROM proyectos WHERE id = $1", proyecto_id)
    base = await presupuesto_base(conn, proyecto_id)
    cfg = await config_vigente(conn, proyecto_id)
    corte = fecha_corte or dt.date.today()

    cab = await conn.fetchrow("SELECT * FROM estado_obra WHERE proyecto_id = $1", proyecto_id)
    ultima = await conn.fetchval(
        "SELECT max(fecha_avance) FROM avances_partida WHERE proyecto_id = $1", proyecto_id
    )
    dias = (corte - ultima).days if ultima else None

    partidas = await conn.fetch(
        """
        SELECT p.codigo_interno, p.codigo_covenin, p.descripcion, p.unidad, p.capitulo,
               p.cantidad AS cantidad_presupuestada,
               COALESCE(eop.cantidad_acumulada, 0) AS cantidad_acumulada,
               COALESCE(eop.pct_fisico_real, 0)    AS pct_real,
               eop.pct_fisico_plan                 AS pct_plan,
               eop.desviacion_pp, eop.ultima_fecha_avance,
               eop.calidad_dato, COALESCE(eop.tiene_evidencia, false) AS tiene_evidencia
          FROM partidas p
          LEFT JOIN estado_obra_partida eop ON eop.partida_id = p.id
         WHERE p.presupuesto_id = $1
           AND ($2::text IS NULL OR upper(p.codigo_interno) = upper($2) OR upper(p.codigo_covenin) = upper($2))
           AND ($3::text IS NULL OR p.capitulo ILIKE $3)
         ORDER BY p.orden, p.codigo_interno
        """,
        base["id"] if base else None, codigo_partida, capitulo,
    )

    salida: dict[str, Any] = {
        "proyecto": {
            "codigo": proyecto["codigo"],
            "nombre_obra": proyecto["nombre_obra"],
            "cliente": proyecto["cliente"],
            "moneda": proyecto["moneda_base"],
            "tipo_obra": proyecto["tipo_obra"],
        },
        "corte": corte.isoformat(),
        "avance_fisico_real_pct": float(cab["pct_fisico_real"]) if cab else 0.0,
        "avance_fisico_plan_pct": float(cab["pct_fisico_plan"]) if cab and cab["pct_fisico_plan"] is not None else None,
        "desviacion_pp": (
            round(float(cab["pct_fisico_real"]) - float(cab["pct_fisico_plan"]), 2)
            if cab and cab["pct_fisico_plan"] is not None else None
        ),
        "avance_financiero_pct": float(cab["pct_financiero"]) if cab else 0.0,
        "monto_ejecutado": float(cab["monto_ejecutado"]) if cab else 0.0,
        "monto_presupuestado": float(cab["monto_presupuestado"]) if cab else 0.0,
        # Regla del dato viejo — estos tres campos vienen siempre.
        "ultima_fecha_avance": ultima.isoformat() if ultima else None,
        "dias_sin_reporte": dias,
        "advertencia_datos": _advertencia_datos(ultima, dias),
        "partidas_sin_avance": int(cab["partidas_sin_avance"]) if cab else len(partidas),
        "bloqueos_abiertos": int(cab["bloqueos_abiertos"]) if cab else 0,
        "avances_en_espera": int(cab["avances_en_espera"]) if cab else 0,
        # Supuestos de configuración que produjeron estos números.
        "configuracion": {
            "base_ponderacion": cfg.get("base_ponderacion"),
            "umbrales_pp": {
                "media": float(cfg.get("umbral_media_pp", 0)),
                "alta": float(cfg.get("umbral_alta_pp", 0)),
                "critica": float(cfg.get("umbral_critica_pp", 0)),
            },
            "dias_sin_reporte_alerta": cfg.get("dias_sin_reporte_alerta"),
            "ratificada_por_sotica": bool(cfg.get("ratificado_por_sotica", False)),
            "nota": (
                None if cfg.get("ratificado_por_sotica")
                else "Umbrales y base de ponderación PENDIENTES DE RATIFICACIÓN POR SOTICA. "
                     "Declararlo como supuesto en todo informe que use estos números."
            ),
        },
        "partidas": [
            {
                "codigo": r["codigo_interno"],
                "codigo_covenin": r["codigo_covenin"],
                "descripcion": r["descripcion"],
                "capitulo": r["capitulo"],
                "unidad": r["unidad"],
                "cantidad_presupuestada": float(r["cantidad_presupuestada"]),
                "cantidad_acumulada": float(r["cantidad_acumulada"]),
                "pct_real": float(r["pct_real"]),
                "pct_plan": float(r["pct_plan"]) if r["pct_plan"] is not None else None,
                "desviacion_pp": float(r["desviacion_pp"]) if r["desviacion_pp"] is not None else None,
                "ultima_fecha_avance": r["ultima_fecha_avance"].isoformat() if r["ultima_fecha_avance"] else None,
                "calidad_dato": r["calidad_dato"],
                "tiene_evidencia": r["tiene_evidencia"],
            }
            for r in partidas
        ],
    }

    if incluir_desviaciones:
        desv = await conn.fetch(
            """
            SELECT d.tipo, d.severidad, d.valor_plan, d.valor_real, d.brecha,
                   d.descripcion, d.impacto_estimado, d.detectada_en, p.codigo_interno
              FROM desviaciones d
              LEFT JOIN partidas p ON p.id = d.partida_id
             WHERE d.proyecto_id = $1 AND d.estado = 'abierta'
             ORDER BY CASE d.severidad WHEN 'critica' THEN 1 WHEN 'alta' THEN 2
                                       WHEN 'media' THEN 3 ELSE 4 END, d.detectada_en DESC
            """,
            proyecto_id,
        )
        salida["desviaciones_abiertas"] = [
            {
                "codigo_partida": r["codigo_interno"],
                "tipo": r["tipo"],
                "severidad": r["severidad"],
                "valor_plan": float(r["valor_plan"]) if r["valor_plan"] is not None else None,
                "valor_real": float(r["valor_real"]) if r["valor_real"] is not None else None,
                "brecha": float(r["brecha"]) if r["brecha"] is not None else None,
                "descripcion": r["descripcion"],
                "impacto_estimado": r["impacto_estimado"],
            }
            for r in desv
        ]
    return salida
