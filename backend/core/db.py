"""Acceso a Postgres. Un único pool compartido por la API y los servidores MCP."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from .config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    # jsonb entra y sale como dict/list, no como str.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=1, max_size=10, init=_init_conn
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def acquire():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction():
    """Todo registro de avance ocurre dentro de una sola transacción:
    o entran el avance, el estado consolidado y las desviaciones, o no entra nada."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


async def fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
    async with acquire() as conn:
        return await conn.fetch(sql, *args)


async def fetchrow(sql: str, *args: Any) -> asyncpg.Record | None:
    async with acquire() as conn:
        return await conn.fetchrow(sql, *args)


async def fetchval(sql: str, *args: Any) -> Any:
    async with acquire() as conn:
        return await conn.fetchval(sql, *args)


async def execute(sql: str, *args: Any) -> str:
    async with acquire() as conn:
        return await conn.execute(sql, *args)


def as_dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
