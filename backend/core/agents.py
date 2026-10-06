"""Registro de agentes sobre Claude Agent SDK.

Los system prompts siguen viviendo en backend/agents/*.md — una sola fuente. El
frontmatter es neutro respecto al SDK (nombres MCP sin prefijo); aquí se traduce
a lo que el Claude Agent SDK espera.

Delegación: **agents-as-tools**. Cada subagente es una herramienta de ORQ-COST
(`delegar_sub_cm`, …) que corre un `query()` anidado: contexto aislado, su propio
allowlist de herramientas MCP, briefing de §5.1 validado en la entrada y
`RespuestaSubagente` exigida como salida estructurada. Se usa este patrón en vez
de los subagentes nativos del SDK porque el briefing nativo es texto libre y el
contrato de §5.1 dejaría de ser un esquema.
"""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    create_sdk_mcp_server,
    query,
    tool,
)
from pydantic import ValidationError

from ..mcp.stdio_server import REGISTROS
from .config import (
    AGENTS_DIR,
    BASE_DIR,
    CICLO_1_AGENTES,
    CLAUDE_CLI,
    MAX_TURNS_SUBAGENTE,
    MODEL,
)
from .contratos import BriefingSOTICA, RespuestaSubagente

SERVIDOR_DELEGACION = "sotica_delegacion"


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
    """ORQ-COST + los subagentes del ciclo 1. Los de fase 2 están escritos y con el
    formato nuevo, pero no se registran hasta quitarles `enabled: false`."""
    return {
        codigo: af
        for codigo, af in cargar_agentes().items()
        if af.enabled and (af.role == "orquestador" or codigo in CICLO_1_AGENTES)
    }


# ---------------------------------------------------------------------------
# Servidores MCP (procesos stdio reales) y permisos por agente
# ---------------------------------------------------------------------------

def _herramientas_de(registro: str) -> list[str]:
    return [h.nombre for h in importlib.import_module(REGISTROS[registro]).registro.listar()]


def _mcp_de_agente(af: AgentFile, mapa: dict[str, str] | None):
    """Servidores stdio, allowlist y denylist de un agente.

    `mapa` traduce nombre de servidor → registro que lo implementa; por defecto
    cada servidor es su propio registro. Los criterios §11 lo usan para apuntar
    `sotica_obra` y `sotica_docs` al registro de fixtures.

    El límite es por agente, no por servidor: lo que el frontmatter no lista se
    deniega explícitamente, así el agente ni siquiera lo ve.
    """
    mapa = mapa or {}
    servidores: dict[str, Any] = {}
    permitidas: list[str] = []
    denegadas: list[str] = []
    pendientes = set(af.tools)
    for nombre in af.mcp_servers:
        registro = mapa.get(nombre, nombre)
        servidores[nombre] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "backend.mcp.stdio_server", registro],
            "env": {"PYTHONPATH": str(BASE_DIR), "PYTHONIOENCODING": "utf-8"},
        }
        for herramienta in _herramientas_de(registro):
            calificado = f"mcp__{nombre}__{herramienta}"
            if herramienta in pendientes:
                pendientes.discard(herramienta)
                permitidas.append(calificado)
            else:
                denegadas.append(calificado)
    if pendientes:
        raise RuntimeError(
            f"{af.codigo}: herramientas sin servidor que las publique: {sorted(pendientes)}"
        )
    return servidores, permitidas, denegadas


def _opciones(af: AgentFile, mapa: dict[str, str] | None, **extra: Any) -> ClaudeAgentOptions:
    servidores, permitidas, denegadas = _mcp_de_agente(af, mapa)
    servidores.update(extra.pop("mcp_servers", {}))
    permitidas += extra.pop("allowed_tools", [])
    return ClaudeAgentOptions(
        system_prompt=extra.pop("system_prompt", af.prompt),
        model=MODEL,
        mcp_servers=servidores,
        strict_mcp_config=True,
        # Nada de filesystem ni shell: estos agentes solo hablan y usan sus herramientas MCP.
        tools=[],
        allowed_tools=permitidas,
        disallowed_tools=denegadas,
        permission_mode="dontAsk",
        setting_sources=None,
        cwd=str(BASE_DIR),
        cli_path=CLAUDE_CLI,
        **extra,
    )


# ---------------------------------------------------------------------------
# Delegación: subagentes como herramientas de ORQ-COST
# ---------------------------------------------------------------------------

def _texto(mensaje: str, es_error: bool = False) -> dict[str, Any]:
    resultado: dict[str, Any] = {"content": [{"type": "text", "text": mensaje}]}
    if es_error:
        resultado["isError"] = True
    return resultado


def _herramienta_de_delegacion(af: AgentFile, mapa: dict[str, str] | None):
    opciones = _opciones(
        af,
        mapa,
        max_turns=MAX_TURNS_SUBAGENTE,
        output_format={"type": "json_schema", "schema": RespuestaSubagente.model_json_schema()},
    )

    @tool(
        af.tool_name,
        f"{af.description}\n\n"
        "Recibe el briefing completo de §5.1 y devuelve resultado, método, supuestos, "
        "fuentes, nivel de confianza y bloqueos. El subagente NO ve la conversación "
        "con el usuario: todo lo que necesite saber va en el briefing.",
        BriefingSOTICA.model_json_schema(),
    )
    async def delegar(args: dict[str, Any]) -> dict[str, Any]:
        try:
            briefing = BriefingSOTICA(**args)
        except ValidationError as exc:
            return _texto(f"Briefing incompleto (§5.1): {exc}", es_error=True)

        final: ResultMessage | None = None
        async for msg in query(prompt=briefing.render(), options=opciones):
            if isinstance(msg, ResultMessage):
                final = msg
        if final is None or final.is_error:
            motivo = (final.result or final.subtype) if final else "sin respuesta"
            return _texto(f"{af.codigo} no pudo completar la tarea: {motivo}", es_error=True)
        if final.structured_output is not None:
            try:
                salida = RespuestaSubagente.model_validate(final.structured_output)
                return _texto(salida.model_dump_json(indent=2))
            except ValidationError:
                return _texto(json.dumps(final.structured_output, ensure_ascii=False, indent=2))
        return _texto(str(final.result or ""))

    return delegar


def opciones_orquestador(
    contexto_obra: str, mapa: dict[str, str] | None = None, **extra: Any
) -> ClaudeAgentOptions:
    """Opciones de ORQ-COST con los subagentes del ciclo cableados como herramientas."""
    archivos = activos()
    if "ORQ-COST" not in archivos:
        raise RuntimeError("Falta backend/agents/orq-cost.md o está deshabilitado")
    orq = archivos["ORQ-COST"]

    subagentes = [
        archivos[c] for c in orq.subagentes
        if c in archivos and archivos[c].role == "subagente"
    ]
    delegacion = create_sdk_mcp_server(
        SERVIDOR_DELEGACION,
        tools=[_herramienta_de_delegacion(af, mapa) for af in subagentes],
    )
    return _opciones(
        orq,
        mapa,
        system_prompt=orq.prompt + "\n\n---\n\n" + contexto_obra,
        mcp_servers={SERVIDOR_DELEGACION: delegacion},
        allowed_tools=[f"mcp__{SERVIDOR_DELEGACION}__{af.tool_name}" for af in subagentes],
        **extra,
    )


def nombre_corto(herramienta: str) -> str:
    """`mcp__sotica_obra__consultar_estado_obra` → `consultar_estado_obra`."""
    return herramienta.rsplit("__", 1)[-1]
