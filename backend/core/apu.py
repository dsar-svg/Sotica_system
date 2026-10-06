"""Análisis de precio unitario (SOTICA-APU-01) con evidencia por renglón.

El sistema no trae catálogo de precios: cada número lo carga una persona y aquí
se decide, con reglas fijas y no con criterio del modelo, qué etiqueta de dato
le corresponde. Un precio de proveedor sin proveedor, enlace y fecha entra como
`pendiente_confirmacion` y no suma al total firme del presupuesto.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import asyncpg

from . import computo, control

# De peor a mejor: la partida hereda la etiqueta más débil de sus renglones.
_ORDEN = ["pendiente_confirmacion", "inferido", "referencial", "confirmado"]
_POR_RENDIMIENTO = {"equipo", "mano_obra"}


def _fecha(valor: Any) -> dt.date | None:
    return dt.date.fromisoformat(str(valor)) if valor else None


def clasificar(r: dict[str, Any], registrado_por: str) -> tuple[str, str, list[str]]:
    """Devuelve (etiqueta, fuente, evidencia faltante) de un renglón."""
    origen = r["origen"]
    fecha = r.get("fecha_consulta")
    if origen == "cotizacion_proveedor":
        falta = [c for c in ("proveedor", "enlace", "fecha_consulta") if not r.get(c)]
        fuente = f"Cotización {r.get('proveedor') or 'SIN PROVEEDOR'}" + (
            f", consultada el {fecha}" if fecha else ""
        )
        return ("pendiente_confirmacion" if falta else "confirmado"), fuente, falta
    if origen == "experiencia_obra":
        return "inferido", f"Experiencia de obra — {registrado_por}", []
    if origen == "historico_sotica":
        if not r.get("fuente"):
            return "pendiente_confirmacion", "Histórico SOTICA sin obra de referencia", ["fuente"]
        return "referencial", f"Histórico SOTICA — {r['fuente']}", []
    if origen == "referencial_civ":
        if not fecha:
            raise ValueError(
                f"'{r['descripcion']}': un precio referencial exige fecha_consulta "
                "(la fecha de la base de precios)."
            )
        return "referencial", f"{r.get('fuente') or 'Guía referencial CIV-DataLaing'} ({fecha})", []
    if origen == "consulta_internet":
        if not r.get("enlace") or not fecha:
            raise ValueError(
                f"'{r['descripcion']}': un precio de internet solo se registra con el enlace "
                "de la página donde se encontró y la fecha de consulta. Sin enlace no hay precio."
            )
        sitio = r.get("proveedor") or r["enlace"].split("/")[2]
        return "referencial", f"Precio aproximado de internet — {sitio} ({fecha})", []
    raise ValueError(f"origen de precio desconocido: {origen!r}")


async def registrar_apu(
    conn: asyncpg.Connection,
    proyecto_ref: str,
    codigo_partida: str,
    registrado_por: str,
    renglones: list[dict[str, Any]],
    rendimiento: float | None = None,
    fcas_pct: float | None = None,
) -> dict[str, Any]:
    registrado_por = (registrado_por or "").strip()
    if not registrado_por:
        raise ValueError("Falta registrado_por: todo precio lleva el nombre de quien lo cargó.")
    if not renglones:
        raise ValueError("Un APU sin renglones no es un APU.")

    proyecto = await control.proyecto_por_ref(conn, proyecto_ref)
    if proyecto is None:
        raise ValueError(f"No existe la obra '{proyecto_ref}'.")
    presupuesto = await computo._borrador(conn, proyecto)
    partida = await control.buscar_partida(conn, presupuesto["id"], codigo_partida)
    if partida is None:
        raise ValueError(
            f"La partida '{codigo_partida}' no está en el presupuesto borrador "
            f"v{presupuesto['version']}. Primero se computa (SUB-CM), luego se le pone precio."
        )

    filas: list[tuple] = []
    pendientes: list[dict[str, Any]] = []
    directo = mano_obra = 0.0
    for r in renglones:
        tipo = r["tipo"]
        cantidad, precio = float(r["cantidad"]), float(r["precio_unitario"])
        desperdicio = float(r.get("desperdicio_pct") or 0)
        if tipo in _POR_RENDIMIENTO:
            if not rendimiento or rendimiento <= 0:
                raise ValueError(
                    f"'{r['descripcion']}' es {tipo}: su costo por unidad depende del "
                    "rendimiento de la partida (unidades por día). Falta `rendimiento`."
                )
            if cantidad < 0.2:
                # Error típico: mandar 1/rendimiento como cantidad. El rendimiento ya divide;
                # aceptarlo dividiría dos veces y dejaría la mano de obra casi en cero.
                raise ValueError(
                    f"'{r['descripcion']}': en {tipo} la `cantidad` es el NÚMERO de recursos "
                    f"(1 albañil, 2 ayudantes, 0.5 si es medio tiempo), no la fracción por "
                    f"unidad de partida. Llegó {cantidad}. El costo por unidad lo calcula la "
                    "herramienta: cantidad × costo por día ÷ rendimiento."
                )
            subtotal = cantidad * precio / float(rendimiento)
        else:
            subtotal = cantidad * (1 + desperdicio / 100.0) * precio
        etiqueta, fuente, falta = clasificar(r, registrado_por)
        if falta:
            pendientes.append({"renglon": r["descripcion"], "falta": falta})
        directo += subtotal
        if tipo == "mano_obra":
            mano_obra += subtotal
        filas.append((
            tipo, r["descripcion"], r["unidad"], cantidad,
            float(rendimiento) if tipo in _POR_RENDIMIENTO else None, desperdicio, precio,
            round(subtotal, 4), etiqueta, fuente, _fecha(r.get("fecha_consulta")),
            r["origen"], r.get("proveedor"), r.get("enlace"), registrado_por,
        ))

    # El FCAS no se supone: si SOTICA no lo dio, la mano de obra va sin recargo y se declara.
    recargo_fcas = mano_obra * float(fcas_pct) / 100.0 if fcas_pct is not None else 0.0
    costo = round(directo + recargo_fcas, 4)
    etiqueta_partida = min((f[8] for f in filas), key=_ORDEN.index)

    await conn.execute("DELETE FROM apu_renglones WHERE partida_id = $1", partida["id"])
    await conn.executemany(
        """
        INSERT INTO apu_renglones (partida_id, tipo, descripcion, unidad, cantidad, rendimiento,
                                   desperdicio_pct, precio_unitario, subtotal, etiqueta, fuente,
                                   fecha_fuente, origen, proveedor, enlace, registrado_por)
        VALUES ($1,$2::tipo_insumo,$3,$4,$5,$6,$7,$8,$9,$10::etiqueta_dato,$11,$12,
                $13::origen_precio,$14,$15,$16)
        """,
        [(partida["id"], *f) for f in filas],
    )
    await conn.execute(
        """
        UPDATE partidas SET precio_unitario = $2, etiqueta_precio = $3::etiqueta_dato,
               fuente_precio = $4, apu_rendimiento = $5, apu_fcas_pct = $6
         WHERE id = $1
        """,
        partida["id"], costo, etiqueta_partida,
        f"APU SOTICA-APU-01 — {len(filas)} renglones, cargado por {registrado_por}",
        rendimiento, fcas_pct,
    )

    avisos = []
    de_internet = [f[1] for f in filas if f[11] == "consulta_internet"]
    if de_internet:
        avisos.append(
            "Precios APROXIMADOS tomados de internet (referenciales, no son cotización): "
            + ", ".join(de_internet) + ". Conviene confirmarlos con cotización de proveedor."
        )
    if pendientes:
        avisos.append(
            "Hay precios sin evidencia completa: la partida queda con precio PENDIENTE DE "
            "CONFIRMACIÓN y no suma al total firme del presupuesto."
        )
    if mano_obra and fcas_pct is None:
        avisos.append(
            "FCAS no definido: la mano de obra va sin recargo. SOTICA debe indicar el FCAS "
            "de su plantilla para este tipo de obra."
        )
    return {
        "presupuesto": {"version": presupuesto["version"], "estado": presupuesto["estado"]},
        "partida": partida["codigo_interno"],
        "unidad": partida["unidad"],
        "costo_directo_unitario": costo,
        "desglose": {"renglones": round(directo, 4), "recargo_fcas": round(recargo_fcas, 4)},
        "aporte_por_renglon": [
            {"tipo": f[0], "insumo": f[1], "aporte_al_precio_unitario": f[7], "etiqueta": f[8]}
            for f in filas
        ],
        "etiqueta_precio": etiqueta_partida,
        "monto_partida": round(costo * float(partida["cantidad"]), 2),
        "evidencia_pendiente": pendientes,
        "avisos": avisos,
        "nota": "Costo directo. Administración, utilidad e impuestos se aplican a nivel de "
                "presupuesto y los define SOTICA.",
    }
