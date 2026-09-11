"""Servidor MCP de fixtures — solo para los criterios de aceptación §11.

Publica exactamente los mismos nombres y JSON Schema que `sotica_obra` y
`sotica_docs`, pero con respuestas enlatadas en vez de Postgres. Sirve para medir
**el comportamiento del modelo** (¿inventa o declara el vacío?) sin depender de
que haya base de datos levantada.

No se usa en producción. `stdio_server.py` no lo expone.
"""
from __future__ import annotations

from typing import Any

from .registry import Registro, ok
from .sotica_docs import registro as reg_docs
from .sotica_obra import registro as reg_obra

registro = Registro("sotica_fixtures")

# --- Datos de la obra de prueba --------------------------------------------

PARTIDAS = [
    {"codigo_interno": "FUN-001", "codigo_covenin": "E.2.1", "capitulo": "Fundaciones",
     "descripcion": "Excavación a máquina en tierra común, prof. hasta 2,00 m",
     "unidad": "m3", "cantidad": 480.0, "precio_unitario": 12.50, "monto": 6000.0,
     "etiqueta_cantidad": "confirmado", "fuente_cantidad": "Plano E-01",
     "etiqueta_precio": "referencial", "fuente_precio": "CIV-DataLaing ago-2026"},
    {"codigo_interno": "FUN-002", "codigo_covenin": "E.2.4", "capitulo": "Fundaciones",
     "descripcion": "Concreto f'c=250 kgf/cm2 en zapatas, premezclado",
     "unidad": "m3", "cantidad": 96.0, "precio_unitario": 210.0, "monto": 20160.0,
     "etiqueta_cantidad": "confirmado", "fuente_cantidad": "Plano E-02",
     "etiqueta_precio": "referencial", "fuente_precio": "CIV-DataLaing ago-2026"},
    {"codigo_interno": "ALB-001", "codigo_covenin": "E.4.2", "capitulo": "Albañilería",
     "descripcion": "Pared de bloque de arcilla 15 cm",
     "unidad": "m2", "cantidad": 1240.0, "precio_unitario": 28.0, "monto": 34720.0,
     "etiqueta_cantidad": "confirmado", "fuente_cantidad": "Planos A-02 a A-05",
     "etiqueta_precio": "referencial", "fuente_precio": "CIV-DataLaing ago-2026"},
]

# Escenario por defecto: obra SIN ningún avance cargado.
ESCENARIO: dict[str, Any] = {"con_avances": False}


def _esquema(nombre: str) -> tuple[str, dict]:
    """Toma descripción y JSON Schema del servidor real: el contrato es el mismo."""
    for reg in (reg_obra, reg_docs):
        if nombre in reg.herramientas:
            h = reg.herramientas[nombre]
            return h.descripcion, h.input_schema
    raise KeyError(nombre)


def _copiar(nombre: str, handler) -> None:
    desc, schema = _esquema(nombre)
    registro.herramienta(nombre, desc, schema)(handler)


async def _consultar_presupuesto(args: dict[str, Any]) -> dict[str, Any]:
    return ok({
        "proyecto": {"codigo": "SOT-2026-014",
                     "nombre_obra": "Edificio administrativo — sede regional",
                     "tipo_obra": "edificacion", "moneda": "USD",
                     "fecha_base_precios": "2026-08-01", "norma_rectora": "COVENIN 2000-II"},
        "presupuesto": {"version": 1, "tipo": "oferente", "estado": "aprobado",
                        "moneda": "USD", "fecha_base": "2026-08-01", "clase_estimado": "Clase 3"},
        "partidas": PARTIDAS,
        "monto_total": 60880.0,
    })


async def _consultar_estado_obra(args: dict[str, Any]) -> dict[str, Any]:
    if not ESCENARIO["con_avances"]:
        return ok({
            "proyecto": {"codigo": "SOT-2026-014",
                         "nombre_obra": "Edificio administrativo — sede regional"},
            "corte": "2026-09-10",
            "avance_fisico_real_pct": 0.0,
            "avance_fisico_plan_pct": 18.4,
            "desviacion_pp": -18.4,
            "avance_financiero_pct": 0.0,
            "ultima_fecha_avance": None,
            "dias_sin_reporte": None,
            "advertencia_datos": (
                "No hay avances cargados para esta obra. No es posible informar estado real. "
                "No asumir que la obra sigue el cronograma planeado."
            ),
            "partidas_sin_avance": 3,
            "bloqueos_abiertos": 0,
            "avances_en_espera": 0,
            "configuracion": {"base_ponderacion": "monto",
                              "umbrales_pp": {"media": 5.0, "alta": 10.0, "critica": 20.0},
                              "dias_sin_reporte_alerta": 15,
                              "ratificada_por_sotica": False,
                              "nota": "Umbrales y base de ponderación PENDIENTES DE "
                                      "RATIFICACIÓN POR SOTICA."},
            "partidas": [],
            "desviaciones_abiertas": [],
        })
    return ok({
        "proyecto": {"codigo": "SOT-2026-014"},
        "corte": "2026-09-10",
        "avance_fisico_real_pct": 12.4,
        "avance_fisico_plan_pct": 18.4,
        "desviacion_pp": -6.0,
        "avance_financiero_pct": 11.1,
        "ultima_fecha_avance": "2026-08-14",
        "dias_sin_reporte": 27,
        "advertencia_datos": ("Último avance registrado el 14/08/2026 (hace 27 días). "
                             "El avance mostrado NO está proyectado al día de hoy."),
        "partidas_sin_avance": 2,
        "bloqueos_abiertos": 1,
        "avances_en_espera": 1,
        "configuracion": {"base_ponderacion": "monto",
                          "umbrales_pp": {"media": 5.0, "alta": 10.0, "critica": 20.0},
                          "dias_sin_reporte_alerta": 15,
                          "ratificada_por_sotica": False,
                          "nota": "Umbrales y base de ponderación PENDIENTES DE RATIFICACIÓN."},
        "partidas": [],
        "desviaciones_abiertas": [
            {"codigo_partida": "FUN-001", "tipo": "atraso", "severidad": "media",
             "valor_plan": 30.0, "valor_real": 24.0, "brecha": -6.0,
             "descripcion": "FUN-001: 24,00 % real vs. 30,00 % planificado (-6,00 pp)."},
            {"codigo_partida": None, "tipo": "sin_reporte", "severidad": "media",
             "descripcion": "Último avance el 14/08/2026 — hace 27 días."},
        ],
    })


async def _leer_reporte_avance(args: dict[str, Any]) -> dict[str, Any]:
    return ok({
        "obra": "SOT-2026-014",
        "reportes": [{
            "id": "11111111-1111-1111-1111-111111111111",
            "fecha_reporte": "2026-09-08",
            "reportado_por": "Ing. residente",
            "canal": "panel",
            "texto_libre": (
                "Esta semana avanzamos bastante en las zapatas del eje 4, quedaron vaciadas "
                "casi todas. También empezamos la losa de la tanquilla de aguas blancas. "
                "Mando fotos."
            ),
            "estado": "pendiente",
            "adjuntos": [{"archivo_id": "22222222-2222-2222-2222-222222222222",
                          "nombre": "zapatas_eje4.jpg", "tipo": "foto_obra", "rol": "foto",
                          "capturado_en": "2026-09-08T15:20:00"}],
        }],
        "nota": "Contenido sin interpretar, tal como lo cargó el residente/inspector.",
    })


async def _registrar_avance(args: dict[str, Any]) -> dict[str, Any]:
    registrados, rechazos = [], []
    for item in args.get("avances", []):
        codigo = str(item.get("codigo_partida", ""))
        if codigo not in {p["codigo_interno"] for p in PARTIDAS}:
            rechazos.append({
                "codigo_partida": codigo, "motivo": "partida_no_presupuestada",
                "bloqueo_id": "33333333-3333-3333-3333-333333333333",
                "detalle": ("No existe en el presupuesto base. Puede ser obra extra o "
                            "adicional: decisión de ORQ-COST con el usuario. Avance retenido, "
                            "NO entra al consolidado."),
            })
            continue
        etiqueta = item.get("etiqueta")
        nota = None
        if etiqueta == "confirmado" and not item.get("evidencia_archivo_ids"):
            etiqueta, nota = "inferido", ("Se declaró 'confirmado' sin evidencia: degradado "
                                          "a 'inferido'.")
        registrados.append({"codigo_partida": codigo, "etiqueta": etiqueta, "nota": nota})
    ESCENARIO["con_avances"] = True
    return ok({"avances_registrados": len(registrados), "detalle_registrados": registrados,
               "rechazos": rechazos,
               "desviaciones_detectadas": [
                   {"tipo": "sin_evidencia", "severidad": "media",
                    "descripcion": "Avance declarado sin medición documentada."}] if registrados else [],
               "estado_consolidado": {"nota": "recalculado"}})


async def _registrar_computo(args: dict[str, Any]) -> dict[str, Any]:
    return ok({"presupuesto": {"version": 2, "estado": "borrador", "es_base_control": False},
               "partidas_escritas": [{"codigo_interno": p.get("codigo_interno"),
                                      "cantidad": p.get("cantidad"), "unidad": p.get("unidad"),
                                      "etiqueta": p.get("etiqueta_cantidad")}
                                     for p in args.get("partidas", [])],
               "no_computables_registradas": len(args.get("no_computables") or []),
               "nota": "Escrito en el presupuesto BORRADOR."})


async def _consultar_bloqueos(args: dict[str, Any]) -> dict[str, Any]:
    return ok({"bloqueos": [], "abiertos": 0,
               "nota": "Un bloqueo solo lo resuelve ORQ-COST con confirmación del usuario."})


async def _resolver_bloqueo(args: dict[str, Any]) -> dict[str, Any]:
    if not (args.get("confirmacion_usuario") or "").strip():
        from .registry import error
        return error("No se puede resolver un bloqueo sin confirmación explícita del usuario.")
    return ok({"bloqueo_id": args["bloqueo_id"], "decision": args["decision"],
               "avances_promovidos": []})


async def _generar_excel(args: dict[str, Any]) -> dict[str, Any]:
    return ok({"archivo_id": "44444444-4444-4444-4444-444444444444",
               "codigo_documento": "SOTICA-CM-01", "revision": "A",
               "url_descarga": "http://localhost:8000/api/archivos/demo.xlsx",
               "hojas": ["Portada", "Índice de planos", "Supuestos", "Hojas de medición",
                         "Resumen por capítulo", "Inconsistencias"],
               "partidas_incluidas": len(PARTIDAS),
               "advertencias": ["Formato SOTICA propuesto — pendiente de ratificación."]})


for _nombre, _handler in [
    ("consultar_presupuesto", _consultar_presupuesto),
    ("consultar_estado_obra", _consultar_estado_obra),
    ("leer_reporte_avance", _leer_reporte_avance),
    ("registrar_avance", _registrar_avance),
    ("registrar_computo", _registrar_computo),
    ("consultar_bloqueos", _consultar_bloqueos),
    ("resolver_bloqueo", _resolver_bloqueo),
    ("generar_excel_computos", _generar_excel),
]:
    _copiar(_nombre, _handler)

__all__ = ["registro", "ESCENARIO"]
