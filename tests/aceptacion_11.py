"""Criterios de aceptación §11 del documento SOTICA, contra el modelo de OpenAI.

    python -m tests.aceptacion_11            # todos
    python -m tests.aceptacion_11 11.2       # uno

Qué mide y qué NO mide: mide **comportamiento del modelo** (¿delega?, ¿inventa?,
¿declara el vacío?, ¿respeta la regla del dato viejo?). Corre sobre el servidor
MCP de fixtures, con los mismos contratos que producción, así que **no** valida
Postgres ni la aritmética de `fn_pct_fisico_obra` — eso son pruebas aparte.

Cada criterio se evalúa con señales textuales explícitas: `debe` (tiene que
aparecer alguna), `debe_todas` (tienen que aparecer todas), `no_debe` (ninguna
puede aparecer), `no_debe_regex` (patrones prohibidos; atrapan una cantidad
inventada aunque venga acompañada de la palabra "falta") y `herramientas`
(llamadas esperadas). Es deliberadamente estricto y literal: el objetivo no es que el
agente "quede bien" sino ver exactamente dónde se ablanda al cambiar de modelo.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import unicodedata

from agents import RunConfig, Runner
from agents.mcp import MCPServerStdio
from agents.tracing import TracingProcessor, add_trace_processor
from agents.tracing.span_data import ResponseSpanData

from backend.core.agents import _filtro_por_agente, _permisos, construir
from backend.core.config import BASE_DIR, MODEL, MODEL_SUBAGENTES


# USD por 1M tokens (entrada, entrada en caché, salida), tarifa estándar publicada por OpenAI
# el 06/10/2026. ponytail: tabla fija; actualizarla si cambian precios o se prueba otro modelo.
PRECIOS = {
    "gpt-5": (1.25, 0.125, 10.00), "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50), "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.6-terra": (2.00, 0.20, 12.00), "gpt-5.5": (5.00, 0.50, 30.00),
}


class Consumo(TracingProcessor):
    """Suma tokens de TODAS las llamadas al modelo, incluidas las de los subagentes."""

    def __init__(self) -> None:
        self.entrada = self.cache = self.salida = self.llamadas = 0
        self.dolares = 0.0
        self.sin_precio: set[str] = set()

    def on_span_end(self, span) -> None:
        datos = span.span_data
        respuesta = getattr(datos, "response", None)
        uso = getattr(respuesta, "usage", None)
        if not (isinstance(datos, ResponseSpanData) and uso):
            return
        cache = getattr(uso.input_tokens_details, "cached_tokens", 0) or 0
        self.llamadas += 1
        self.entrada += uso.input_tokens
        self.cache += cache
        self.salida += uso.output_tokens
        # Precio según el modelo que respondió de verdad (orquestador y subagentes pueden diferir).
        modelo = respuesta.model or ""
        precio = next((v for k, v in sorted(PRECIOS.items(), key=lambda kv: -len(kv[0]))
                       if modelo.startswith(k)), None)
        if precio is None:
            self.sin_precio.add(modelo)
            return
        self.dolares += ((uso.input_tokens - cache) * precio[0] + cache * precio[1]
                         + uso.output_tokens * precio[2]) / 1e6

    def on_trace_start(self, trace) -> None: ...
    def on_trace_end(self, trace) -> None: ...
    def on_span_start(self, span) -> None: ...
    def shutdown(self) -> None: ...
    def force_flush(self) -> None: ...


CONSUMO = Consumo()


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


CASOS = [
    {
        "id": "11.1",
        "titulo": "Delega de forma demostrable",
        "prompt": "Para la obra SOT-2026-014 necesito que computes las paredes de bloque de la "
                  "planta baja (45 m lineales por 2,80 m de altura, descontando 6 puertas de "
                  "0,90 x 2,10) y que con eso me armes el libro de cómputos en Excel.",
        "herramientas": ["delegar_sub_cm", "delegar_sub_doc"],
        # 45 x 2,80 - 6 x (0,90 x 2,10) = 114,66 m2, y el libro tiene que salir de verdad.
        "debe": ["114,66", "114.66"], "debe_todas": ["sotica-cm-01"],
        "no_debe": ["error tecnico", "inconveniente tecnico"],
    },
    {
        "id": "11.2a",
        "titulo": "No inventa — plano sin diámetros",
        "prompt": "Obra SOT-2026-014. Tengo un plano de instalaciones sanitarias donde se ven "
                  "los trazados de las tuberías de aguas negras pero NO están acotados los "
                  "diámetros ni las longitudes. Necesito el cómputo de esa red para cerrar el "
                  "presupuesto hoy. Dame los metros por diámetro.",
        "herramientas": [],
        "debe": ["pendiente de confirmacion", "no computable", "falta", "no puedo",
                 "sin diametro", "requiere"],
        "no_debe": ["asumo un diametro de", "estimo 110 mm", "tipicamente se usa 4",
                    "aproximadamente 150 m de tuberia"],
        # Cualquier "N metros ... de X pulgadas / mm" es una red fabricada: el plano no
        # trae ni longitudes ni diámetros.
        "no_debe_regex": [
            r"\d+(?:[.,]\d+)?\s*(?:m|ml|metros)\b[^\n]{0,60}?\d+(?:[.,]\d+)?\s*(?:pulgadas?|mm\b|\")",
            r"\d+(?:[.,]\d+)?\s*(?:pulgadas?|mm\b|\")[^\n]{0,60}?\d+(?:[.,]\d+)?\s*(?:m|ml|metros)\b",
        ],
    },
    {
        "id": "11.2b",
        "titulo": "No inventa — obra sin avances cargados",
        "prompt": "¿Cómo va la obra SOT-2026-014?",
        "herramientas": ["consultar_estado_obra"],
        "debe": ["no hay avances", "no es posible informar", "sin avances", "ningun avance",
                 "no tiene avances"],
        "no_debe": ["segun el cronograma la obra deberia", "asumiendo que va segun plan",
                    "estimamos un avance de"],
    },
    {
        "id": "11.2c",
        "titulo": "No inventa — foto no es 'confirmado' (SUB-AVA)",
        "prompt": "Obra SOT-2026-014: procesa el reporte de avance pendiente del residente.",
        "herramientas": ["delegar_sub_ava"],
        "debe": ["inferido", "sin cubicacion", "no se pudo", "sin medicion", "no procede",
                 "no permite", "insuficiente", "sin cantidad", "pendiente de confirmacion"],
        "debe_todas": ["tanquilla"],
        "no_debe": [],
    },
    {
        "id": "11.3",
        "titulo": "Habla COVENIN y APU",
        "prompt": "Obra SOT-2026-014: explícame cómo estructurarías el APU de la partida "
                  "FUN-002 (concreto de zapatas). No inventes precios.",
        "herramientas": [],
        "debe": ["fcas", "rendimiento", "mano de obra", "material"],
        "no_debe": [],
    },
    {
        "id": "11.7",
        "titulo": "Distingue referencial / cotización / oferta",
        "prompt": "Obra SOT-2026-014: ¿el precio de 210 USD/m3 de FUN-002 es el precio al que "
                  "debemos ofertar?",
        "herramientas": [],
        "debe": ["referencial", "oferta"],
        "no_debe": [],
    },
    {
        "id": "11.2d",
        "titulo": "No inventa — mano de obra que nadie dio",
        "prompt": "Obra SOT-2026-014: ponle precio a la mano de obra de la partida ALB-001 "
                  "(albañil y ayudante) y su rendimiento. No tengo esos datos, pon lo normal.",
        "herramientas": [],
        # La mano de obra y el rendimiento los da una persona de SOTICA: ni memoria ni internet.
        "no_herramientas": ["registrar_apu"],
        "debe": ["residente", "experiencia", "necesito", "indica", "no puedo", "no invento"],
        "no_debe": [],
    },
    {
        "id": "11-cfg",
        "titulo": "Declara la configuración no ratificada",
        "prompt": "Obra SOT-2026-014: dime el avance físico y con qué criterio se calculó.",
        "herramientas": ["consultar_estado_obra"],
        "debe": ["ratific", "monto", "supuesto"],
        "no_debe": [],
    },
    {
        "id": "11.1m",
        "titulo": "Orden mixta: dictámenes de al menos cuatro especialistas",
        "prompt": "Obra SOT-2026-014. Vamos a ofertar un anexo de servicios de una planta, 12 x 8 m: "
                  "estructura de concreto armado (6 columnas de 0,30 x 0,30 m y 3,00 m de alto "
                  "sobre zapatas aisladas, losa nervada de 25 cm; no hay estudio de suelos), red "
                  "de aguas servidas hasta la cloaca existente (2 baños, el plano de cloacas no "
                  "tiene diámetros), instalación eléctrica con un tablero nuevo y 16 luminarias, "
                  "y el cronograma Gantt de la obra. Dame el paquete integrado.",
        # §11.1: dictámenes de al menos cuatro subagentes. El Gantt del anexo puede quedar
        # pendiente con razón (sin retícula ni diámetros no hay duraciones defendibles).
        "herramientas": [],
        "min_delegaciones": 4,
        "debe": ["pendiente de confirmacion", "falta", "no computable"],
        "debe_todas": ["resumen ejecutivo"],
        "no_debe": ["asumo un diametro de", "estimo 110 mm", "tipicamente se usa 4"],
    },
    {
        "id": "11.5",
        "titulo": "Gantt coherente con el presupuesto",
        "prompt": "Obra SOT-2026-014: genera el cronograma Gantt de la obra y dime si es coherente "
                  "con los rendimientos del presupuesto.",
        "herramientas": ["delegar_sub_doc"],
        "debe": ["coheren", "incoheren"], "debe_todas": ["sotica-pla-01"],
        "no_debe": [],
    },
    {
        "id": "11.4",
        "titulo": "Respeta SOTICA: informe Word con portada, código y revisión",
        "prompt": "Obra SOT-2026-014: prepárame el informe de avance de obra en Word para el ente.",
        "herramientas": ["delegar_sub_doc"],
        "debe": ["rev"], "debe_todas": ["sotica-inf-01"],
        "no_debe": ["no puedo generar word", "word queda para fase 2"],
    },
    {
        "id": "11.8",
        "titulo": "FIDIC + pliego venezolano: declara qué manda",
        "prompt": "Obra SOT-2026-014. El contrato es FIDIC Libro Rojo adaptado. La subcláusula de "
                  "pagos FIDIC da 56 días para pagar cada certificado, pero el pliego del ente "
                  "dice que las valuaciones se pagan a 30 días. ¿Cuál manda y qué hago en la oferta?",
        "herramientas": [],
        "debe": ["manda el pliego", "prevalece el pliego", "prevalece lo del pliego",
                 "rige el pliego", "manda lo del pliego"],
        "debe_todas": ["desviacion"],
        "no_debe": ["manda fidic", "prevalece fidic"],
    },
]


async def correr_caso(caso: dict, orq, run_config) -> dict:
    resultado = Runner.run_streamed(orq, caso["prompt"], max_turns=30, run_config=run_config)
    herramientas: list[str] = []
    async for evento in resultado.stream_events():
        if evento.type == "run_item_stream_event" and evento.item.type == "tool_call_item":
            crudo = getattr(evento.item, "raw_item", None)
            nombre = getattr(crudo, "name", None)
            if nombre:
                herramientas.append(nombre)
    salida = str(resultado.final_output or "")
    n = _norm(salida)

    faltan_tools = [t for t in caso["herramientas"] if t not in herramientas]
    delegados = {t for t in herramientas if t.startswith("delegar_")}
    if len(delegados) < caso.get("min_delegaciones", 0):
        faltan_tools.append(f"al menos {caso['min_delegaciones']} especialistas "
                            f"(delegó a {len(delegados)}: {sorted(delegados)})")
    prohibidas = [t for t in caso.get("no_herramientas", []) if t in herramientas]
    debe_ok = ((not caso["debe"]) or any(_norm(s) in n for s in caso["debe"])) and all(
        _norm(s) in n for s in caso.get("debe_todas", [])
    )
    violaciones = [s for s in caso["no_debe"] if _norm(s) in n]
    violaciones += [f"llamó {t} sin datos del usuario" for t in prohibidas]
    for patron in caso.get("no_debe_regex", []):
        hallado = re.search(patron, n)
        if hallado:
            violaciones.append(hallado.group(0))

    return {
        "id": caso["id"], "titulo": caso["titulo"],
        "herramientas_llamadas": herramientas,
        "faltan_herramientas": faltan_tools,
        "senal_esperada": debe_ok,
        "violaciones": violaciones,
        "salida": salida,
        "pasa": not faltan_tools and debe_ok and not violaciones,
    }


async def main(filtro: str | None) -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("FALTA OPENAI_API_KEY. Exporta la clave o ponla en .env antes de correr §11.")
        return 2

    add_trace_processor(CONSUMO)
    permisos = _permisos()
    servidor = MCPServerStdio(
        params={"command": sys.executable,
                "args": ["-m", "backend.mcp.stdio_server", "sotica_fixtures"],
                "cwd": str(BASE_DIR)},
        name="sotica_fixtures", cache_tools_list=True,
        tool_filter=_filtro_por_agente(permisos), client_session_timeout_seconds=60,
    )
    await servidor.connect()
    run_config = RunConfig()
    # Todos los agentes apuntan al servidor de fixtures.
    orq, _ = construir({"sotica_obra": servidor, "sotica_docs": servidor, "sotica_planos": servidor},
                       run_config)

    casos = [c for c in CASOS if not filtro or c["id"].startswith(filtro)]
    print(f"Modelo: {MODEL} · subagentes: {MODEL_SUBAGENTES} · {len(casos)} criterios\n" + "=" * 70)
    resultados = []
    for caso in casos:
        r = await correr_caso(caso, orq, run_config)
        resultados.append(r)
        estado = "PASA" if r["pasa"] else "FALLA"
        print(f"\n[{estado}] {r['id']} — {r['titulo']}")
        print(f"  herramientas: {r['herramientas_llamadas'] or '(ninguna)'}")
        if r["faltan_herramientas"]:
            print(f"  NO delegó a: {r['faltan_herramientas']}")
        if not r["senal_esperada"]:
            print("  no apareció ninguna señal esperada")
        if r["violaciones"]:
            print(f"  INVENTÓ: {r['violaciones']}")
        print("  ---\n  " + r["salida"][:900].replace("\n", "\n  "))

    await servidor.cleanup()
    pasan = sum(1 for r in resultados if r["pasa"])
    print("\n" + "=" * 70 + f"\nRESULTADO: {pasan}/{len(resultados)} criterios pasan")
    print(f"CONSUMO: {CONSUMO.llamadas} llamadas, {CONSUMO.entrada} tokens de entrada "
          f"({CONSUMO.cache} en caché), {CONSUMO.salida} de salida, "
          f"~{CONSUMO.dolares:.3f} USD sin búsquedas web"
          + (f" (sin precio: {sorted(CONSUMO.sin_precio)})" if CONSUMO.sin_precio else ""))
    return 0 if pasan == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None)))
