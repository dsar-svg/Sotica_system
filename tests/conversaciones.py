"""Conversaciones con historial y presupuestos abiertos desde el chat (requiere Postgres, no OpenAI).

Crea una conversación general, le carga un historial como lo guarda el SDK, abre un presupuesto
con la herramienta MCP y la enlaza. Al final borra lo que creó.

Corre con:  .venv\\Scripts\\python.exe -m tests.conversaciones
"""
from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core import db, orchestrator
from backend.mcp import sotica_obra

HISTORIAL = [
    {"role": "user", "content": "¿Cuánto cuesta el saco de cemento en Barquisimeto?"},
    {"type": "web_search_call", "id": "ws_1", "status": "completed", "action": {"type": "search"}},
    {"type": "message", "role": "assistant", "id": "m1", "status": "completed",
     "content": [{"type": "output_text", "text": "Alrededor de 9 USD [referencial].", "annotations": []}]},
    {"role": "user", "content": "Ármame el presupuesto de un galpón de 20 x 30 m"},
    {"type": "function_call", "name": "crear_presupuesto", "call_id": "c1", "arguments": "{}"},
    {"type": "message", "role": "assistant", "id": "m2", "status": "completed",
     "content": [{"type": "output_text", "text": "Abrí el presupuesto.", "annotations": []}]},
]


async def preparar() -> tuple[str, str]:
    salida = await sotica_obra.crear_presupuesto(
        {"nombre_obra": "Galpón de prueba 20 x 30", "cliente": "Constructora Privada"})
    datos = json.loads(salida["content"][0]["text"])
    codigo = datos["presupuesto_creado"]
    assert datos["cliente_registrado"], datos
    assert orchestrator._CREADO.search(salida["content"][0]["text"]).group(1) == codigo
    cid = await db.fetchval("INSERT INTO conversaciones (titulo) VALUES ('prueba') RETURNING id")
    await orchestrator.sesion_conversacion(str(cid)).add_items(HISTORIAL)
    await soltar()
    return str(cid), codigo


async def soltar() -> None:
    # Cada asyncio.run tiene su propio loop: el pool y el engine no pueden pasar de uno a otro.
    await db.close_pool()
    if orchestrator._engine is not None:
        await orchestrator._engine.dispose()
        orchestrator._engine = None


async def limpiar(cid: str, codigo: str) -> None:
    await orchestrator.sesion_conversacion(cid).clear_session()
    await db.execute("DELETE FROM conversaciones WHERE id = $1::uuid", cid)
    await db.execute("DELETE FROM proyectos WHERE codigo = $1", codigo)
    await soltar()


def main() -> None:
    cid, codigo = asyncio.run(preparar())
    try:
        with TestClient(app) as c:
            lista = c.get("/api/conversaciones").json()
            assert any(x["id"] == cid and x["codigo"] is None for x in lista), "conversación general"

            conv = c.get(f"/api/conversaciones/{cid}").json()
            m = conv["mensajes"]
            assert [x["rol"] for x in m] == ["yo", "orq", "yo", "orq"], m
            assert m[1]["herramientas"] == ["busqueda_web"] and "9 USD" in m[1]["texto"]
            assert m[3]["herramientas"] == ["crear_presupuesto"]

            r = c.patch(f"/api/conversaciones/{cid}", json={"proyecto": codigo}).json()
            assert r["proyecto"] == codigo
            p = {x["codigo"]: x for x in c.get("/api/proyectos").json()}[codigo]
            assert p["fase"] == "oportunidad" and p["ultima_conversacion"] == cid
            assert c.patch(f"/api/conversaciones/{cid}", json={"proyecto": None}).json()["proyecto"] is None

            assert c.delete(f"/api/conversaciones/{cid}").json()["ok"]
            assert c.get(f"/api/conversaciones/{cid}").status_code == 404
            assert c.get("/api/conversaciones/no-es-uuid").status_code == 404
    finally:
        orchestrator._engine = None  # quedó atado al loop del TestClient
        asyncio.run(limpiar(cid, codigo))
    print(f"[OK] conversaciones: historial, enlace a {codigo} y borrado")


if __name__ == "__main__":
    main()
