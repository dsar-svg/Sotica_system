"""Contrato interno entre agentes — §5.1 del documento SOTICA.

Antes era prosa que ORQ-COST tenía que acordarse de escribir. Ahora es un
esquema que el SDK valida: si el briefing va incompleto, la llamada no sale, y
si el subagente responde sin nivel de confianza o sin fuentes, no compila la
respuesta. La migración endurece §5.1 en vez de debilitarla.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BriefingSOTICA(BaseModel):
    """Lo que ORQ-COST entrega al delegar. Todos los campos de §5.1 son obligatorios
    salvo los que pueden estar legítimamente vacíos (documentos, prohibiciones)."""

    codigo_proyecto: str = Field(description="Código de obra, p. ej. SOT-2026-014")
    nombre_obra: str
    producto_solicitado: str = Field(
        description="Pregunta o producto exacto. No 'ayúdame con esto': el entregable concreto."
    )
    documentos_disponibles: list[str] = Field(
        default_factory=list,
        description="Planos, memorias, pliegos, fotos o archivo_id disponibles para el subagente.",
    )
    norma_rectora: str = Field(description="COVENIN 2000-II, pliego del ente, FIDIC…")
    unidades: str = Field(default="SI", description="Sistema de medición")
    moneda: str
    fecha_base: str = Field(description="Fecha base de precios, YYYY-MM-DD")
    prohibido_inferir: list[str] = Field(
        default_factory=list,
        description=(
            "Lo que el subagente NO puede deducir aunque le falte: diámetros no dibujados, "
            "cargas eléctricas no indicadas, resultados de laboratorio inexistentes."
        ),
    )
    formato_respuesta: str = Field(
        default="cantidades / criterio / riesgos / preguntas al usuario",
        description="Forma esperada del entregable del subagente.",
    )

    def render(self) -> str:
        doc = "\n".join(f"  - {d}" for d in self.documentos_disponibles) or "  - (ninguno aportado)"
        proh = "\n".join(f"  - {d}" for d in self.prohibido_inferir) or "  - (sin prohibiciones explícitas; aplica igual la regla de no inventar)"
        return f"""BRIEFING DE DELEGACIÓN — ORQ-COST

Proyecto: {self.codigo_proyecto} — {self.nombre_obra}
Producto solicitado: {self.producto_solicitado}

Documentos disponibles:
{doc}

Norma o pliego rector: {self.norma_rectora}
Unidades / sistema de medición: {self.unidades}
Moneda: {self.moneda} · Fecha base de precios: {self.fecha_base}

PROHIBIDO INFERIR:
{proh}

Formato de respuesta esperado: {self.formato_respuesta}

Responde con: resultado, método, supuestos, fuentes, nivel de confianza y bloqueos.
Si no puedes resolver con certeza, declara el vacío y qué haría falta. No rellenes.
"""


class Supuesto(BaseModel):
    texto: str
    etiqueta: Literal["confirmado", "inferido", "referencial", "pendiente_confirmacion"]
    fuente: str | None = None


class Bloqueo(BaseModel):
    descripcion: str
    que_falta: str = Field(description="Qué dato o decisión desbloquearía esta línea")
    impacto_estimado: str | None = None


class RespuestaSubagente(BaseModel):
    """Lo que todo subagente devuelve. §5.1: resultado, método, supuestos, fuentes,
    nivel de confianza y bloqueos. El nivel de confianza no es opcional."""

    resultado: str = Field(description="El entregable en sí, en español técnico venezolano.")
    metodo: str = Field(description="Cómo se llegó al resultado; auditable por un inspector.")
    supuestos: list[Supuesto] = Field(default_factory=list)
    fuentes: list[str] = Field(
        default_factory=list,
        description="Plano y corte, norma, base de precios con fecha, o instrucción del usuario.",
    )
    nivel_confianza: Literal["alto", "medio", "bajo"]
    bloqueos: list[Bloqueo] = Field(default_factory=list)
    preguntas_al_usuario: list[str] = Field(
        default_factory=list,
        description="Máximo 5, priorizadas por impacto en el monto (§10.1 'pregunta mínima').",
    )
