"""Registrar una partida ya computada no borra el cómputo anterior (requiere Postgres).

Todo corre en una transacción que se revierte: no deja rastro en la base.

Corre con:  .venv\\Scripts\\python.exe -m tests.computo_modos
"""
from __future__ import annotations

import asyncio

import asyncpg

from backend.core.computo import registrar_computo
from backend.core.config import DATABASE_URL


def _partida(referencia: str, expresiones: list[str], etiqueta: str, modo: str | None = None):
    p = {"codigo_interno": "ALB-T01", "capitulo": "Albañilería", "descripcion": "Pared de bloque",
         "unidad": "m2", "cantidad": 0, "etiqueta_cantidad": etiqueta, "fuente_cantidad": referencia,
         "mediciones": [{"referencia": referencia, "expresion": e, "subtotal": 0,
                         "etiqueta": etiqueta} for e in expresiones]}
    if modo:
        p["modo"] = modo
    return [p]


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute("INSERT INTO proyectos (codigo, nombre_obra, fecha_base_precios) "
                           "VALUES ('SOT-TEST-MODOS', 'prueba', DATE '2026-10-01')")
        pb = _partida("Planta baja", ["45*2.8", "-6*(0.9*2.1)"], "confirmado")
        r = await registrar_computo(conn, "SOT-TEST-MODOS", pb, [])
        assert r["partidas_escritas"][0]["cantidad"] == 114.66

        pa = ["60*2.8", "-4*(0.9*2.1)", "-6*(1.5*1.2)"]
        try:
            await registrar_computo(conn, "SOT-TEST-MODOS", _partida("Planta alta", pa, "inferido"), [])
            raise AssertionError("sin modo debió rechazar")
        except ValueError as exc:
            assert "modo='agregar'" in str(exc) and "114.66" in str(exc), exc

        r = await registrar_computo(
            conn, "SOT-TEST-MODOS", _partida("Planta alta", pa, "inferido", "agregar"), [])
        escrita = r["partidas_escritas"][0]
        assert escrita["cantidad"] == 264.30, escrita        # 114,66 + 149,64
        assert escrita["mediciones"] == 5 and escrita["etiqueta"] == "inferido", escrita

        r = await registrar_computo(
            conn, "SOT-TEST-MODOS", _partida("Planta baja corregida", ["40*2.8"], "confirmado",
                                             "reemplazar"), [])
        assert r["partidas_escritas"][0]["cantidad"] == 112.0
        assert r["partidas_escritas"][0]["mediciones"] == 1
        print("[OK] modos agregar / reemplazar de registrar_computo")
    finally:
        await tx.rollback()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
