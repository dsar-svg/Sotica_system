"""Arranque de ORQ-COST sobre el Claude Agent SDK.

Una sesión por obra: el orquestador conserva el contexto del proyecto (moneda,
ente, plantilla FCAS, formatos ratificados) entre mensajes, como pide §10.1.
Los subagentes son nativos del SDK, con contexto aislado y su propio allowlist.
"""
from __future__ import annotations

import datetime as dt
from typing import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from ..mcp import sotica_docs, sotica_obra
from . import db
from .agents import herramientas_permitidas, prompt_orquestador, subagentes_activos
from .config import MODEL


def construir_opciones(contexto_obra: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=prompt_orquestador() + "\n\n---\n\n" + contexto_obra,
        agents=subagentes_activos(),
        mcp_servers={
            "sotica_obra": sotica_obra.servidor,
            "sotica_docs": sotica_docs.servidor,
        },
        allowed_tools=herramientas_permitidas(),
        # Nada de filesystem ni shell: este agente solo habla y usa sus herramientas.
        disallowed_tools=["Bash", "Write", "Edit", "Read", "WebSearch", "WebFetch"],
        permission_mode="dontAsk",
        model=MODEL,
        setting_sources=None,
        max_turns=40,
    )


async def contexto_obra(proyecto_ref: str | None) -> str:
    """Memoria de proyecto que se antepone al prompt del orquestador."""
    if not proyecto_ref:
        return (
            "## Contexto de sesión\n"
            "No hay obra seleccionada. Antes de computar, presupuestar o informar avance, "
            "pide al usuario que indique la obra (código SOT-XXXX-NNN)."
        )

    from . import control  # import diferido para evitar ciclo

    async with db.acquire() as conn:
        p = await control.proyecto_por_ref(conn, proyecto_ref)
        if p is None:
            return f"## Contexto de sesión\nLa obra '{proyecto_ref}' no existe en el sistema."
        base = await control.presupuesto_base(conn, p["id"])
        cfg = await control.config_vigente(conn, p["id"])
        bloqueos = await conn.fetchval(
            "SELECT count(*) FROM bloqueos WHERE proyecto_id=$1 AND estado='abierto'", p["id"]
        )
        ultima = await conn.fetchval(
            "SELECT max(fecha_avance) FROM avances_partida WHERE proyecto_id=$1", p["id"]
        )

    dias = (dt.date.today() - ultima).days if ultima else None
    return f"""## Contexto de sesión — memoria de proyecto

- Obra: **{p['nombre_obra']}** (`{p['codigo']}`)
- Cliente / ente: {p['cliente'] or '—'} · Tipo de obra: {p['tipo_obra']}
- Moneda base: {p['moneda_base']} · Fecha base de precios: {p['fecha_base_precios']:%d/%m/%Y}
- Plantilla FCAS: {p['plantilla_fcas'] or 'no definida'} · Norma rectora: {p['norma_rectora'] or 'COVENIN 2000'}
- Formatos SOTICA ratificados: {'sí' if p['formatos_ratificados'] else 'NO — usar juego propuesto §7.2 y marcarlo'}
- Presupuesto base de control: {'v' + str(base['version']) if base else 'NO DEFINIDO — el seguimiento de obra no puede medir sin él'}
- Último avance registrado: {ultima.strftime('%d/%m/%Y') + f' (hace {dias} días)' if ultima else 'NINGUNO'}
- Bloqueos abiertos: {bloqueos}
- Umbrales de desviación (pp): {cfg.get('umbral_media_pp')} / {cfg.get('umbral_alta_pp')} / {cfg.get('umbral_critica_pp')} · Ponderación: {cfg.get('base_ponderacion')} · Ratificados por SOTICA: {'sí' if cfg.get('ratificado_por_sotica') else 'NO'}

Cuando llames a una herramienta, usa `proyecto = "{p['codigo']}"`.
"""


class SesionObra:
    """Sesión de chat viva contra ORQ-COST, atada a una obra."""

    def __init__(self, proyecto_ref: str | None = None) -> None:
        self.proyecto_ref = proyecto_ref
        self._client: ClaudeSDKClient | None = None

    async def abrir(self) -> None:
        opciones = construir_opciones(await contexto_obra(self.proyecto_ref))
        self._client = ClaudeSDKClient(options=opciones)
        await self._client.connect()

    async def cerrar(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def preguntar(self, mensaje: str) -> AsyncIterator[dict]:
        """Emite eventos {tipo, ...} para que la API los reenvíe como SSE."""
        if self._client is None:
            await self.abrir()
        assert self._client is not None

        await self._client.query(mensaje)
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for bloque in msg.content:
                    if isinstance(bloque, TextBlock):
                        yield {"tipo": "texto", "texto": bloque.text}
                    elif getattr(bloque, "type", None) == "tool_use":
                        yield {
                            "tipo": "herramienta",
                            "nombre": getattr(bloque, "name", "?"),
                            "entrada": getattr(bloque, "input", {}),
                        }
            elif isinstance(msg, ResultMessage):
                yield {"tipo": "fin", "resultado": getattr(msg, "subtype", None)}
