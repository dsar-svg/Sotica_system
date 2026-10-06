"""Registro de agentes sobre OpenAI Agents SDK.

Los system prompts siguen viviendo en backend/agents/*.md — una sola fuente. Lo
único que cambió con la migración es el frontmatter y cómo se lo damos al SDK.

Delegación: **agents-as-tools**, no handoffs. Un handoff transfiere la
conversación y el control no vuelve, lo que rompería §2 (el usuario solo habla
con el orquestador), §5.2 (ORQ-COST resuelve contradicciones) y la invocación en
paralelo de §2.3. Con agents-as-tools cada subagente corre en un run anidado
—contexto aislado, igual que los subagentes nativos anteriores— y devuelve su
dictamen a ORQ-COST, que consolida.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from agents import Agent, RunConfig, Runner, WebSearchTool, function_tool
from agents.mcp import MCPServerStdio

from .config import (
    AGENTS_DIR,
    BASE_DIR,
    BUSCAR_PRECIOS_EN_INTERNET,
    MAX_TURNS_SUBAGENTE,
    MODEL,
    MODEL_SUBAGENTES,
)
from .contratos import BriefingSOTICA, RespuestaSubagente


@dataclass
class AgentFile:
    codigo: str
    role: str
    enabled: bool
    description: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    tool_name: str | None = None
    subagentes: list[str] = field(default_factory=list)


def _parse(path: Path) -> AgentFile:
    texto = path.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        raise ValueError(f"{path.name}: falta el frontmatter YAML")
    _, frontmatter, cuerpo = texto.split("---", 2)
    meta: dict[str, Any] = yaml.safe_load(frontmatter) or {}
    return AgentFile(
        codigo=meta["name"],
        role=meta.get("role", "subagente"),
        enabled=bool(meta.get("enabled", True)),
        description=(meta.get("description") or "").strip(),
        prompt=cuerpo.strip(),
        tools=list(meta.get("tools") or []),
        mcp_servers=list(meta.get("mcp_servers") or []),
        tool_name=meta.get("tool_name"),
        subagentes=list(meta.get("subagentes") or []),
    )


def cargar_agentes() -> dict[str, AgentFile]:
    return {af.codigo: af for af in (_parse(p) for p in sorted(AGENTS_DIR.glob("*.md")))}


def activos() -> dict[str, AgentFile]:
    """Agentes con `enabled: true` en su archivo de prompt."""
    return {codigo: af for codigo, af in cargar_agentes().items() if af.enabled}


# ---------------------------------------------------------------------------
# Servidores MCP (procesos stdio reales)
# ---------------------------------------------------------------------------

def _permisos() -> dict[str, set[str]]:
    """Qué herramientas MCP puede ver cada agente. Sustituye al allowlist del
    SDK anterior: el límite sigue siendo por agente, no por servidor."""
    return {af.codigo: set(af.tools) for af in activos().values()}


def _filtro_por_agente(permisos: dict[str, set[str]]):
    """Filtro dinámico: un solo proceso por servidor MCP, pero cada agente ve
    únicamente sus herramientas. Sin esto habría que levantar un proceso por
    (agente, servidor)."""

    def filtro(context, tool) -> bool:
        agente = getattr(context, "agent", None)
        nombre_agente = getattr(agente, "name", None)
        if nombre_agente is None:
            return False
        return getattr(tool, "name", "") in permisos.get(nombre_agente, set())

    return filtro


def servidores_requeridos() -> list[str]:
    requeridos: set[str] = set()
    for af in activos().values():
        requeridos.update(af.mcp_servers)
    return sorted(requeridos)


def crear_servidores_mcp() -> dict[str, MCPServerStdio]:
    """Un proceso por servidor MCP, lanzado con el intérprete del entorno actual."""
    import sys

    permisos = _permisos()
    filtro = _filtro_por_agente(permisos)
    servidores: dict[str, MCPServerStdio] = {}
    for nombre in servidores_requeridos():
        servidores[nombre] = MCPServerStdio(
            params={
                "command": sys.executable,
                "args": ["-m", "backend.mcp.stdio_server", nombre],
                "cwd": str(BASE_DIR),
            },
            name=nombre,
            cache_tools_list=True,
            tool_filter=filtro,
            client_session_timeout_seconds=60,
        )
    return servidores


# ---------------------------------------------------------------------------
# Construcción de agentes
# ---------------------------------------------------------------------------

async def _registrar_delegacion(
    destino: str, briefing: BriefingSOTICA, salida: Any, herramientas: list[str]
) -> None:
    """Deja constancia de la delegación (§5.3 y §10.1 "registro de delegaciones").
    Es bitácora: si la base no está disponible, la delegación no se cae por esto."""
    from . import db  # import diferido: los criterios §11 corren sin Postgres

    respuesta = salida.model_dump() if isinstance(salida, RespuestaSubagente) else None
    if respuesta is not None:
        # Qué herramientas llamó de verdad el subagente: es lo que distingue "lo hizo"
        # de "dijo que lo hizo".
        respuesta["herramientas_usadas"] = herramientas
    try:
        await db.execute(
            """
            INSERT INTO delegaciones (proyecto_id, agente_origen, agente_destino, briefing,
                                      respuesta, confianza, finalizada_en)
            VALUES ((SELECT id FROM proyectos WHERE codigo = $1), 'ORQ-COST',
                    $2::codigo_agente, $3, $4, $5::nivel_confianza, now())
            """,
            briefing.codigo_proyecto, destino, briefing.model_dump(), respuesta,
            respuesta["nivel_confianza"] if respuesta else None,
        )
    except Exception:  # noqa: BLE001
        pass


def _herramienta_de_delegacion(subagente: Agent, af: AgentFile, run_config: RunConfig | None):
    """Convierte un subagente en herramienta de ORQ-COST.

    Se implementa explícitamente (en vez de `Agent.as_tool()` a secas) para poder
    tipar el briefing de §5.1 en la entrada y exigir el formato de respuesta de
    §5.1 en la salida. `Runner.run` sin `session` garantiza el contexto aislado:
    el subagente no ve la conversación del usuario, solo su briefing.
    """

    @function_tool(
        name_override=af.tool_name,
        description_override=(
            f"{af.description}\n\n"
            "Recibe el briefing completo de §5.1 y devuelve resultado, método, supuestos, "
            "fuentes, nivel de confianza y bloqueos. El subagente NO ve la conversación "
            "con el usuario: todo lo que necesite saber va en el briefing."
        ),
    )
    async def delegar(briefing: BriefingSOTICA) -> str:
        resultado = await Runner.run(
            subagente,
            briefing.render(),
            max_turns=MAX_TURNS_SUBAGENTE,
            run_config=run_config,
        )
        salida = resultado.final_output
        usadas = [
            getattr(item.raw_item, "name", "?")
            for item in resultado.new_items if item.type == "tool_call_item"
        ]
        await _registrar_delegacion(af.codigo, briefing, salida, usadas)
        if isinstance(salida, RespuestaSubagente):
            return salida.model_dump_json(indent=2)
        return str(salida)

    return delegar


def _servidores_de(af: AgentFile, servidores: dict[str, MCPServerStdio]) -> list[MCPServerStdio]:
    """Servidores del agente, sin repetir proceso: si dos nombres apuntan al mismo
    servidor (los criterios §11 lo hacen con fixtures), el SDK vería cada
    herramienta duplicada y rechazaría al agente."""
    unicos: list[MCPServerStdio] = []
    for nombre in af.mcp_servers:
        servidor = servidores.get(nombre)
        if servidor is not None and all(servidor is not u for u in unicos):
            unicos.append(servidor)
    return unicos


def construir(
    servidores: dict[str, MCPServerStdio], run_config: RunConfig | None = None
) -> tuple[Agent, dict[str, Agent]]:
    """Devuelve (ORQ-COST, subagentes). Los subagentes quedan cableados como
    herramientas del orquestador."""
    archivos = activos()
    if "ORQ-COST" not in archivos:
        raise RuntimeError("Falta backend/agents/orq-cost.md o está deshabilitado")

    subagentes: dict[str, Agent] = {}
    for codigo, af in archivos.items():
        if af.role != "subagente":
            continue
        subagentes[codigo] = Agent(
            name=codigo,
            instructions=af.prompt,
            model=MODEL_SUBAGENTES,
            mcp_servers=_servidores_de(af, servidores),
            output_type=RespuestaSubagente,
        )

    orq_file = archivos["ORQ-COST"]
    herramientas = [
        _herramienta_de_delegacion(subagentes[codigo], archivos[codigo], run_config)
        for codigo in orq_file.subagentes
        if codigo in subagentes
    ]

    if BUSCAR_PRECIOS_EN_INTERNET:
        herramientas.append(WebSearchTool())

    orquestador = Agent(
        name="ORQ-COST",
        instructions=orq_file.prompt,
        model=MODEL,
        mcp_servers=_servidores_de(orq_file, servidores),
        tools=herramientas,
    )
    return orquestador, subagentes
