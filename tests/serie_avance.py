"""La curva S real reconstruida por fecha coincide con el avance oficial (requiere Postgres).

Inserta avances de prueba en la obra demo dentro de una transacción que se revierte.

Corre con:  .venv\\Scripts\\python.exe -m tests.serie_avance
"""
from __future__ import annotations

import asyncio
import datetime as dt

import asyncpg

from backend.core import control
from backend.core.config import DATABASE_URL


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        p = await control.proyecto_por_ref(conn, "SOT-2026-014")
        base = await control.presupuesto_base(conn, p["id"])
        partidas = {r["codigo_interno"]: r for r in await conn.fetch(
            "SELECT * FROM partidas WHERE presupuesto_id = $1", base["id"])}
        rep = await conn.fetchval(
            "INSERT INTO reportes_avance (proyecto_id, reportado_por, fecha_reporte) "
            "VALUES ($1, 'prueba', DATE '2026-10-03') RETURNING id", p["id"])
        for codigo, fecha, cant in (("FUN-001", "2026-09-12", 200), ("FUN-001", "2026-09-26", 280),
                                    ("FUN-002", "2026-10-03", 33.6)):
            await conn.execute(
                "INSERT INTO avances_partida (reporte_id, proyecto_id, partida_id, fecha_avance, "
                "cantidad_periodo, unidad, metodo, etiqueta, confianza) "
                "VALUES ($1,$2,$3,$4,$5,$6,'prueba','confirmado','alto')",
                rep, p["id"], partidas[codigo]["id"], dt.date.fromisoformat(fecha), cant,
                partidas[codigo]["unidad"])
            await control.recalcular_partida(conn, partidas[codigo]["id"], dt.date(2026, 10, 6))
        await control.recalcular_obra(conn, p["id"], dt.date(2026, 10, 6))
        oficial = float(await conn.fetchval("SELECT fn_pct_fisico_obra($1)", p["id"]))

        d = await control.serie_avance(conn, p["id"], hoy=dt.date(2026, 10, 6))
        ultimo = [x for x in d["serie"] if x.get("ultimo")][0]
        assert ultimo["fecha"] == "2026-10-03", ultimo
        assert abs(ultimo["real"] - oficial) < 0.01, (ultimo["real"], oficial)
        reales = [x["real"] for x in d["serie"] if x["real"] is not None]
        assert reales == sorted(reales), "la curva real acumulada no puede bajar"
        assert all(x["real"] is None for x in d["serie"] if x["fecha"] > "2026-10-03"), "no se proyecta"
        assert any(x["plan"] for x in d["serie"]), "falta el plan"
        fun = {c["capitulo"]: c for c in d["capitulos"]}["Fundaciones"]
        assert fun["pct_real"] > 0 and len(d["partidas"]) == 5
        print(f"[OK] serie de avance: real al último avance {ultimo['real']} % = oficial {oficial} %")
    finally:
        await tx.rollback()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
