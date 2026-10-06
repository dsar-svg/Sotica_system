"""Arranque de ORQ-COST sobre Claude Agent SDK.

Una sesión **persistente por obra**: el SDK guarda el historial de la
conversación y aquí se recuerda qué sesión corresponde a cada obra, para
retomarla tras un reinicio. Si el usuario pregunta "¿cómo va tal obra?" tres
días después, el contexto sigue ahí.

Los subagentes se invocan como herramientas (agents-as-tools) con contexto
aislado: ven su briefing, no la conversación del usuario.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from . import db
from .agents import nombre_corto, opciones_orquestador
from .config import MAX_TURNS_ORQUESTADOR, STORAGE_DIR

_SESIONES = STORAGE_DIR / ".sesiones.json"


def _sesiones_guardadas() -> dict[str, str]:
    try:
        return json.loads(_SESIONES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_sesion(clave: str, session_id: str) -> None:
    sesiones = _sesiones_guardadas()
    if sesiones.get(clave) == session_id:
        return
    sesiones[clave] = session_id
    _SESIONES.parent.mkdir(parents=True, exist_ok=True)
    _SESIONES.write_text(json.dumps(sesiones, indent=2), encoding="utf-8")


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
        self._clave = f"obra:{proyecto_ref or '_sin_obra'}"
        self._client: ClaudeSDKClient | None = None

    async def abrir(self) -> None:
        contexto = await contexto_obra(self.proyecto_ref)
        previa = _sesiones_guardadas().get(self._clave)
        try:
            await self._conectar(contexto, previa)
        except Exception:  # noqa: BLE001 — la sesión previa pudo haberse borrado
            if previa is None:
                raise
            await self._conectar(contexto, None)

    async def _conectar(self, contexto: str, resume: str | None) -> None:
        opciones = opciones_orquestador(
            contexto, max_turns=MAX_TURNS_ORQUESTADOR, resume=resume
        )
        self._client = ClaudeSDKClient(options=opciones)
        await self._client.connect()

    async def cerrar(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001 — cerrar no debe romper el apagado
                pass
            self._client = None

    async def preguntar(self, mensaje: str) -> AsyncIterator[dict]:
        """Emite eventos {tipo, ...} — mismo contrato SSE que antes, para no tocar
        el frontend."""
        if self._client is None:
            await self.abrir()
        assert self._client is not None

        await self._client.query(mensaje)
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for bloque in msg.content:
                    if isinstance(bloque, TextBlock):
                        yield {"tipo": "texto", "texto": bloque.text}
                    elif isinstance(bloque, ToolUseBlock):
                        yield {
                            "tipo": "herramienta",
                            "nombre": nombre_corto(bloque.name),
                            "entrada": {},
                        }
            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    _guardar_sesion(self._clave, msg.session_id)
                if msg.is_error:
                    yield {"tipo": "error", "texto": msg.result or msg.subtype}
                yield {"tipo": "fin", "resultado": msg.subtype}
