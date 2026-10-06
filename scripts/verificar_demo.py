"""Chequeo previo a la demo: base, obra demo, clave de OpenAI y región de salida.

    python -m scripts.verificar_demo
"""
from __future__ import annotations

import asyncio
import sys

import asyncpg
from openai import OpenAI

from backend.core.config import DATABASE_URL, MODEL


async def _base() -> str:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        obras = await conn.fetchval("SELECT count(*) FROM proyectos")
        return f"{obras} obra(s)"
    finally:
        await conn.close()


def main() -> int:
    fallas = 0
    try:
        print(f"ok   base de datos: {asyncio.run(_base())}")
    except Exception as exc:  # noqa: BLE001
        fallas += 1
        print(f"MAL  base de datos: {exc}. ¿Corriste scripts\\db_start.ps1?")
    try:
        OpenAI().responses.create(model=MODEL, input="Responde solo: ok", max_output_tokens=16)
        print(f"ok   OpenAI responde con {MODEL}")
    except Exception as exc:  # noqa: BLE001
        fallas += 1
        texto = str(exc)
        if "unsupported_country_region_territory" in texto:
            texto = "OpenAI bloquea la región de salida a internet: activa la VPN."
        print(f"MAL  OpenAI: {texto[:300]}")
    print("Listo para la demo." if not fallas else f"{fallas} problema(s): resolver antes de empezar.")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
