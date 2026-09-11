"""Registro de herramientas MCP, independiente de cualquier SDK de agentes.

Reemplaza al decorador `@tool` del Claude Agent SDK. El contrato que expone es
el mismo que ya teníamos: nombre, descripción y **JSON Schema explícito**. Los
esquemas no se derivan de anotaciones de tipo a propósito: llevan `enum`,
`required` y descripciones que son parte de las reglas de negocio (qué
etiquetas de dato se aceptan, que la fecha es la del evento en obra y no la de
subida), y eso no se puede perder en una inferencia automática.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class Herramienta:
    nombre: str
    descripcion: str
    input_schema: dict[str, Any]
    handler: Handler


@dataclass
class Registro:
    """Conjunto de herramientas que se publica como un servidor MCP."""

    nombre_servidor: str
    herramientas: dict[str, Herramienta] = field(default_factory=dict)

    def herramienta(self, nombre: str, descripcion: str, input_schema: dict[str, Any]):
        def decorador(fn: Handler) -> Handler:
            self.herramientas[nombre] = Herramienta(nombre, descripcion, input_schema, fn)
            return fn

        return decorador

    def listar(self) -> list[Herramienta]:
        return list(self.herramientas.values())

    async def invocar(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        if nombre not in self.herramientas:
            raise KeyError(f"Herramienta desconocida: {nombre}")
        return await self.herramientas[nombre].handler(argumentos or {})


def ok(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False, indent=2,
                                            default=str)}]}


def error(mensaje: str) -> dict[str, Any]:
    return {"content": [{"type": "text",
                         "text": json.dumps({"error": mensaje}, ensure_ascii=False)}],
            "isError": True}
