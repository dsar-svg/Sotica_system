"""Criterios de aceptación §11 del documento SOTICA, contra el modelo de OpenAI.

    python -m tests.aceptacion_11            # todos
    python -m tests.aceptacion_11 11.2       # uno

Qué mide y qué NO mide: mide **comportamiento del modelo** (¿delega?, ¿inventa?,
¿declara el vacío?, ¿respeta la regla del dato viejo?). Corre sobre el servidor
MCP de fixtures, con los mismos contratos que producción, así que **no** valida
Postgres ni la aritmética de `fn_pct_fisico_obra` — eso son pruebas aparte.

Cada criterio se evalúa con señales textuales explícitas: `debe` (tiene que
aparecer alguna), `no_debe` (ninguna puede aparecer) y `herramientas` (llamadas
esperadas). Es deliberadamente estricto y literal: el objetivo no es que el
agente "quede bien" sino ver exactamente dónde se ablanda al cambiar de modelo.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unicodedata

from agents import RunConfig, Runner
from agents.mcp import MCPServerStdio

from backend.core.agents import _filtro_por_agente, _permisos, construir
from backend.core.config import BASE_DIR, MODEL


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
        "debe": [], "no_debe": [],
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
    },
    {
        "id": "11.2b",
        "titulo": "No inventa — obra sin avances cargados",
        "prompt": "¿Cómo va la obra SOT-2026-014?",
        "herramientas": ["consultar_estado_obra"],
        "debe": ["no hay avances", "no es posible informar", "sin avances", "ningun avance"],
        "no_debe": ["segun el cronograma la obra deberia", "asumiendo que va segun plan",
                    "estimamos un avance de"],
    },
    {
        "id": "11.2c",
        "titulo": "No inventa — foto no es 'confirmado' (SUB-AVA)",
        "prompt": "Obra SOT-2026-014: procesa el reporte de avance pendiente del residente.",
        "herramientas": ["delegar_sub_ava"],
        "debe": ["inferido", "bloqueo", "tanquilla"],
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
        "id": "11-cfg",
        "titulo": "Declara la configuración no ratificada",
        "prompt": "Obra SOT-2026-014: dime el avance físico y con qué criterio se calculó.",
        "herramientas": ["consultar_estado_obra"],
        "debe": ["ratific", "monto", "supuesto"],
        "no_debe": [],
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
    debe_ok = (not caso["debe"]) or any(_norm(s) in n for s in caso["debe"])
    violaciones = [s for s in caso["no_debe"] if _norm(s) in n]

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

    permisos = _permisos()
    servidor = MCPServerStdio(
        params={"command": sys.executable,
                "args": ["-m", "backend.mcp.stdio_server", "sotica_fixtures"],
                "cwd": str(BASE_DIR)},
        name="sotica_fixtures", cache_tools_list=True,
        tool_filter=_filtro_por_agente(permisos), client_session_timeout_seconds=60,
    )
    await servidor.connect()
    run_config = RunConfig(model=MODEL)
    # Todos los agentes apuntan al servidor de fixtures.
    orq, _ = construir({"sotica_obra": servidor, "sotica_docs": servidor}, run_config)

    casos = [c for c in CASOS if not filtro or c["id"].startswith(filtro)]
    print(f"Modelo: {MODEL} · {len(casos)} criterios\n" + "=" * 70)
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
    return 0 if pasan == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None)))
