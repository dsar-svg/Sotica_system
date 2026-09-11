"""Registro de agentes.

Los system prompts viven en backend/agents/*.md — una sola fuente. Este módulo
los lee y los convierte en AgentDefinition del Claude Agent SDK. El código nunca
duplica el texto de un prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import AgentDefinition

from .config import AGENTS_DIR, CICLO_1_AGENTES, MODEL


@dataclass
class AgentFile:
    codigo: str
    description: str
    prompt: str
    tools: list[str]
    role: str
    enabled: bool


def _parse(path: Path) -> AgentFile:
    texto = path.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        raise ValueError(f"{path.name}: falta el frontmatter YAML")
    _, frontmatter, cuerpo = texto.split("---", 2)
    meta: dict[str, Any] = yaml.safe_load(frontmatter) or {}
    return AgentFile(
        codigo=meta["name"],
        description=meta.get("description", "").strip(),
        prompt=cuerpo.strip(),
        tools=list(meta.get("tools") or []),
        role=meta.get("role", "subagente"),
        enabled=bool(meta.get("enabled", True)),
    )


def cargar_agentes() -> dict[str, AgentFile]:
    """Todos los .md de backend/agents, indexados por código (ORQ-COST, SUB-CM...)."""
    archivos = {}
    for path in sorted(AGENTS_DIR.glob("*.md")):
        af = _parse(path)
        archivos[af.codigo] = af
    return archivos


def prompt_orquestador() -> str:
    agentes = cargar_agentes()
    if "ORQ-COST" not in agentes:
        raise RuntimeError("Falta backend/agents/orq-cost.md")
    return agentes["ORQ-COST"].prompt


def subagentes_activos() -> dict[str, AgentDefinition]:
    """Subagentes del ciclo 1. Los de fase 2 están escritos pero no se registran:
    activarlos es quitarlos de `enabled: false` y sumarlos a CICLO_1_AGENTES."""
    definiciones: dict[str, AgentDefinition] = {}
    for codigo, af in cargar_agentes().items():
        if af.role != "subagente" or not af.enabled or codigo not in CICLO_1_AGENTES:
            continue
        definiciones[codigo] = AgentDefinition(
            description=af.description,
            prompt=af.prompt,
            tools=af.tools or None,
            model=MODEL,
        )
    return definiciones


def herramientas_permitidas() -> list[str]:
    """Unión de las herramientas de ORQ-COST y de los subagentes activos.
    Lo que no está aquí, no se puede llamar."""
    permitidas: set[str] = set()
    agentes = cargar_agentes()
    for codigo, af in agentes.items():
        if codigo == "ORQ-COST" or codigo in CICLO_1_AGENTES:
            permitidas.update(af.tools)
    return sorted(permitidas)
