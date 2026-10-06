"""Smoke test del handshake MCP completo contra sotica_planos sin LLM.

Inicia el subproceso `python -m backend.mcp.stdio_server sotica_planos`,
realiza el handshake (initialize + list_tools) y verifica que la herramienta
leer_plano_pdf aparece con el JSON Schema correcto.

No requiere DB ni LLM: solo el handshake. Cuando se invoque la herramienta
con un uuid real, ahi si se necesita DB.

Corre con:  .venv\\Scripts\\python.exe -m tests.smoke_planos_stdio
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.mcp.stdio_server", "sotica_planos"],
        cwd=os.getcwd(),
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"[OK] handshake: servidor={init.server_info.name} "
                  f"v{init.server_info.version}")

            tools = await session.list_tools()
            nombres = [t.name for t in tools.tools]
            print(f"[OK] herramientas publicadas: {nombres}")
            assert "leer_plano_pdf" in nombres, nombres

            leer = next(t for t in tools.tools if t.name == "leer_plano_pdf")
            schema = leer.input_schema
            assert schema["type"] == "object"
            assert "archivo_id" in schema["required"]
            assert "max_paginas" in schema["properties"]
            print("[OK] schema de leer_plano_pdf expone archivo_id (required) y max_paginas")

            # Llamada real: esperamos error estructurado (DB caida o NOT FOUND).
            result = await session.call_tool(
                "leer_plano_pdf",
                {"archivo_id": "00000000-0000-0000-0000-000000000000"},
            )
            assert result.is_error is True, f"esperaba is_error=True, recibi {result}"
            texto = result.content[0].text
            try:
                payload = json.loads(texto)
            except Exception:
                payload = {"raw": texto}
            print(f"[OK] llamada con uuid inexistente: isError=True, "
                  f"contenido={str(payload)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))