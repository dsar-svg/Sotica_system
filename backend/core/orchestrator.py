"""Arranque de ORQ-COST sobre OpenAI Agents SDK.

Cada **conversación** persiste su historial en el mismo Postgres del sistema, no en
memoria del proceso: se puede retomar días después y tras un reinicio. Una conversación
puede pertenecer a un proyecto (presupuesto u obra) o ser general.

Los subagentes se invocan como herramientas (agents-as-tools) con contexto
aislado: ven su briefing, no la conversación del usuario.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import AsyncIterator

from agents import RunConfig, Runner
from agents.extensions.memory import SQLAlchemySession
from agents.mcp import MCPServerStdio
from openai.types.responses import ResponseTextDeltaEvent
from sqlalchemy.ext.asyncio import create_async_engine

from . import db
from .agents import construir, crear_servidores_mcp
from .config import MAX_TURNS_ORQUESTADOR, session_url


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
        pendientes = await conn.fetchval(
            "SELECT count(*) FROM reportes_avance WHERE proyecto_id=$1 AND estado='pendiente'",
            p["id"],
        )

    dias = (dt.date.today() - ultima).days if ultima else None
    fase = {
        "oportunidad": "OFERTA EN ESTUDIO — sin contrato todavía. Se trabaja cómputo, APU, presupuesto "
                       "de oferta y documentos de licitación. No hay control de avance: si piden "
                       "avance, explica que la obra no está adjudicada.",
        "adjudicada": "OBRA ADJUDICADA — en ejecución, con control de avance contra el presupuesto base.",
        "cerrada": "OBRA CERRADA — solo consulta y documentos de cierre.",
        "descartada": "OFERTA DESCARTADA — no se ganó o no se presentó; solo consulta.",
    }.get(p["fase"], p["fase"])
    return f"""## Contexto de sesión — memoria de proyecto

- Proyecto: **{p['nombre_obra']}** (`{p['codigo']}`)
- Fase: {fase}
- Cliente / ente: {p['cliente'] or '—'} · Tipo de obra: {p['tipo_obra']}
- Moneda base: {p['moneda_base']} · Fecha base de precios: {p['fecha_base_precios']:%d/%m/%Y}
- Plantilla FCAS: {p['plantilla_fcas'] or 'no definida'} · Norma rectora: {p['norma_rectora'] or 'COVENIN 2000'}
- Plazo contractual: {f"{p['fecha_inicio_contractual']:%d/%m/%Y} a {p['fecha_fin_contractual']:%d/%m/%Y}" if p['fecha_inicio_contractual'] and p['fecha_fin_contractual'] else 'no definido'}
- Formatos SOTICA ratificados: {'sí' if p['formatos_ratificados'] else 'NO — usar juego propuesto §7.2 y marcarlo'}
- Presupuesto base de control: {'v' + str(base['version']) if base else 'NO DEFINIDO — el seguimiento de obra no puede medir sin él'}
- Último avance registrado: {ultima.strftime('%d/%m/%Y') + f' (hace {dias} días)' if ultima else 'NINGUNO'}
- Bloqueos abiertos: {bloqueos}
- Reportes de campo pendientes de procesar por SUB-AVA: {pendientes}
- Umbrales de desviación (pp): {cfg.get('umbral_media_pp')} / {cfg.get('umbral_alta_pp')} / {cfg.get('umbral_critica_pp')} · Ponderación: {cfg.get('base_ponderacion')} · Ratificados por SOTICA: {'sí' if cfg.get('ratificado_por_sotica') else 'NO'}

Cuando llames a una herramienta, usa `proyecto = "{p['codigo']}"`.
Cuando delegues, el briefing lleva estos datos: no se los preguntes de nuevo al usuario.
"""


_engine = None


def sesion_conversacion(conversacion_id: str) -> SQLAlchemySession:
    """Historial de una conversación. Leerlo o borrarlo no levanta los servidores MCP."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(session_url(), echo=False)
    return SQLAlchemySession(f"conv:{conversacion_id}", engine=_engine, create_tables=True)


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    return "".join(c.get("text", "") for c in contenido or []
                   if isinstance(c, dict) and c.get("type") in ("input_text", "output_text"))


async def historial(conversacion_id: str) -> list[dict]:
    """Turnos para volver a pintar el hilo: lo que escribió el usuario, lo que respondió ORQ-COST
    y las herramientas que usó en cada respuesta."""
    turnos: list[dict] = []
    for it in await sesion_conversacion(conversacion_id).get_items():
        tipo, rol = it.get("type"), it.get("role")
        if rol == "user":
            turnos.append({"rol": "yo", "texto": _texto(it.get("content"))})
            continue
        if not turnos or turnos[-1]["rol"] != "orq":
            turnos.append({"rol": "orq", "texto": "", "herramientas": []})
        t = turnos[-1]
        if rol == "assistant":
            t["texto"] = "\n\n".join(x for x in (t["texto"], _texto(it.get("content"))) if x)
        elif tipo == "function_call":
            t["herramientas"].append(it.get("name"))
        elif tipo == "web_search_call":
            t["herramientas"].append("busqueda_web")
    return [t for t in turnos if t["rol"] == "yo" or t["texto"] or t["herramientas"]]


_CREADO = re.compile(r'"presupuesto_creado":\s*"(SOT-\d{4}-\d{3})"')


class Motor:
    """ORQ-COST con sus servidores MCP: uno por proceso, compartido por todas las conversaciones.
    Cada pregunta trae su conversación (historial) y su proyecto (memoria de proyecto)."""

    def __init__(self) -> None:
        self._servidores: dict[str, MCPServerStdio] = {}
        self._orquestador = None
        self._run_config = RunConfig()

    async def abrir(self) -> None:
        # Los servidores MCP son procesos: se levantan una sola vez.
        self._servidores = crear_servidores_mcp()
        for servidor in self._servidores.values():
            await servidor.connect()
        self._orquestador, _ = construir(self._servidores, self._run_config)

    async def cerrar(self) -> None:
        for servidor in self._servidores.values():
            try:
                await servidor.cleanup()
            except Exception:  # noqa: BLE001 — cerrar no debe romper el apagado
                pass
        self._servidores = {}
        self._orquestador = None

    async def preguntar(self, mensaje: str, conversacion_id: str,
                        proyecto_ref: str | None) -> AsyncIterator[dict]:
        """Emite eventos {tipo, ...} para el SSE del panel. La memoria de proyecto se calcula en
        cada pregunta: si cambió la fase o llegó un avance, ORQ-COST lo ve sin reiniciar nada."""
        if self._orquestador is None:
            await self.abrir()
        orquestador = self._orquestador.clone(
            instructions=self._orquestador.instructions + "\n\n---\n\n"
            + await contexto_obra(proyecto_ref))

        resultado = Runner.run_streamed(
            orquestador,
            mensaje,
            session=sesion_conversacion(conversacion_id),
            max_turns=MAX_TURNS_ORQUESTADOR,
            run_config=self._run_config,
        )

        async for evento in resultado.stream_events():
            if evento.type == "raw_response_event" and isinstance(
                evento.data, ResponseTextDeltaEvent
            ):
                yield {"tipo": "texto", "texto": evento.data.delta}
            elif evento.type == "run_item_stream_event":
                item = evento.item
                if item.type == "tool_call_item":
                    yield {
                        "tipo": "herramienta",
                        "nombre": _nombre_herramienta(item),
                        "entrada": {},
                    }
                elif item.type == "tool_call_output_item":
                    # Un presupuesto abierto desde una conversación general queda enlazado a ella.
                    m = _CREADO.search(str(item.output))
                    if m:
                        yield {"tipo": "proyecto", "codigo": m.group(1)}
        yield {"tipo": "fin", "resultado": "completado"}


def _nombre_herramienta(item) -> str:
    crudo = getattr(item, "raw_item", None)
    if getattr(crudo, "type", None) == "web_search_call":
        return "busqueda_web"
    return getattr(crudo, "name", None) or getattr(item, "name", None) or "herramienta"
