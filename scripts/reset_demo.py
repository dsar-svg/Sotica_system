"""Deja la base en el estado inicial de la demo: esquema limpio + obra SOT-2026-014.

    python -m scripts.reset_demo

BORRA TODO lo que haya en la base apuntada por SOTICA_DATABASE_URL (obras, avances,
entregables registrados e historial de chat). Detener la API antes de correrlo.
"""
from __future__ import annotations

import asyncio

import asyncpg

from backend.core.config import BASE_DIR, DATABASE_URL


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for ruta in ("db/schema.sql", "db/seed/demo.sql"):
            await conn.execute((BASE_DIR / ruta).read_text(encoding="utf-8"))
            print(f"ok  {ruta}")
        obras = await conn.fetchval("SELECT count(*) FROM proyectos")
        partidas = await conn.fetchval("SELECT count(*) FROM partidas")
        print(f"Base lista: {obras} obra(s), {partidas} partidas.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
