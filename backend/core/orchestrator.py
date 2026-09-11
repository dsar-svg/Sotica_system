"""Arranque de ORQ-COST sobre OpenAI Agents SDK.

Una sesión **persistente por obra**: el historial vive en el mismo Postgres del
sistema, no en memoria del proceso. Si el usuario pregunta "¿cómo va tal obra?"
tres días después y tras un reinicio, el contexto sigue ahí.

Los subagentes se invocan como herramientas (agents-as-tools) con contexto
aislado: ven su briefing, no la conversación del usuario.
"""
from __future__ import annotations

import datetime as dt
from typing import AsyncIterator

from agents import RunConfig, Runner
from agents.extensions.memory import SQLAlchemySession
from agents.mcp import MCPServerStdio
from openai.types.responses import ResponseTextDeltaEvent

from . import db
from .agents import construir, crear_servidores_mcp
from .config import MAX_TURNS_ORQUESTADOR, MODEL, session_url


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
Cuando delegues, el briefing lleva estos datos: no se los preguntes de nuevo al usuario.
"""


class SesionObra:
    """Sesión de chat viva contra ORQ-COST, atada a una obra y persistida."""

    def __init__(self, proyecto_ref: str | None = None) -> None:
        self.proyecto_ref = proyecto_ref
        self._servidores: dict[str, MCPServerStdio] = {}
        self._orquestador = None
        self._session: SQLAlchemySession | None = None
        self._run_config = RunConfig(model=MODEL)

    async def abrir(self) -> None:
        # Los servidores MCP son procesos: se levantan una vez por sesión.
        self._servidores = crear_servidores_mcp()
        for servidor in self._servidores.values():
            await servidor.connect()

        orquestador, _ = construir(self._servidores, self._run_config)
        # La memoria de proyecto se antepone a las instrucciones del orquestador.
        orquestador.instructions = (
            orquestador.instructions + "\n\n---\n\n" + await contexto_obra(self.proyecto_ref)
        )
        self._orquestador = orquestador

        self._session = SQLAlchemySession.from_url(
            session_id=f"obra:{self.proyecto_ref or '_sin_obra'}",
            url=session_url(),
            engine_kwargs={"echo": False},
            create_tables=True,
        )

    async def cerrar(self) -> None:
        for servidor in self._servidores.values():
            try:
                await servidor.cleanup()
            except Exception:  # noqa: BLE001 — cerrar no debe romper el apagado
                pass
        self._servidores = {}
        self._orquestador = None

    async def preguntar(self, mensaje: str) -> AsyncIterator[dict]:
        """Emite eventos {tipo, ...} — mismo contrato SSE que antes, para no tocar
        el frontend."""
        if self._orquestador is None:
            await self.abrir()

        resultado = Runner.run_streamed(
            self._orquestador,
            mensaje,
            session=self._session,
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
        yield {"tipo": "fin", "resultado": "completado"}


def _nombre_herramienta(item) -> str:
    crudo = getattr(item, "raw_item", None)
    return getattr(crudo, "name", None) or getattr(item, "name", None) or "herramienta"
