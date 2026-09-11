"""Publica un registro de herramientas como servidor MCP stdio real.

    python -m backend.mcp.stdio_server sotica_obra
    python -m backend.mcp.stdio_server sotica_docs

El runtime de agentes (hoy OpenAI Agents SDK) lanza estos procesos con
`MCPServerStdio`. Al ser MCP de verdad —y no un objeto in-process atado a un
SDK— las mismas herramientas sirven a cualquier cliente que hable el protocolo,
que era el punto de haber puesto MCP como capa de herramientas.

API de `mcp` 2.x: los handlers se pasan al constructor de `Server`
(`on_list_tools` / `on_call_tool`), no como decoradores.
"""
from __future__ import annotations

import asyncio
import sys

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .registry import Registro

REGISTROS: dict[str, str] = {
    "sotica_obra": "backend.mcp.sotica_obra",
    "sotica_docs": "backend.mcp.sotica_docs",
    # Solo para los criterios de aceptación §11: mismos contratos, datos enlatados.
    "sotica_fixtures": "backend.mcp.fixtures",
}


def cargar_registro(nombre: str) -> Registro:
    if nombre not in REGISTROS:
        raise SystemExit(f"Servidor desconocido: {nombre}. Opciones: {', '.join(REGISTROS)}")
    import importlib

    return importlib.import_module(REGISTROS[nombre]).registro


def construir(registro: Registro) -> Server:
    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        # Se publica el JSON Schema explícito tal cual: enums, required y
        # descripciones son parte del contrato de negocio, no decoración.
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=h.nombre,
                    description=h.descripcion,
                    inputSchema=h.input_schema,
                )
                for h in registro.listar()
            ]
        )

    async def on_call_tool(
        ctx, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        try:
            resultado = await registro.invocar(params.name, params.arguments or {})
        except Exception as exc:  # noqa: BLE001 — el agente debe ver el motivo exacto
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(exc))],
                isError=True,
            )
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text=bloque.get("text", ""))
                for bloque in resultado.get("content", [])
            ],
            # Se conserva la semántica original: un error de negocio
            # ("la partida no existe en el presupuesto base") viaja como
            # isError=True con su texto, no como una excepción opaca.
            isError=bool(resultado.get("isError", False)),
        )

    return Server(
        name=registro.nombre_servidor,
        version="1.0.0",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def main(nombre: str) -> None:
    registro = cargar_registro(nombre)
    server = construir(registro)
    async with stdio_server() as (lectura, escritura):
        await server.run(lectura, escritura, server.create_initialization_options())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m backend.mcp.stdio_server <sotica_obra|sotica_docs>")
    asyncio.run(main(sys.argv[1]))
