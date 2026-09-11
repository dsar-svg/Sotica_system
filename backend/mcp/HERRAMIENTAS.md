# Herramientas MCP — Ciclo funcional 1

MCP es **la capa de herramientas**, no el orquestador. Cada servidor se conecta a Postgres con su propio
rol, de modo que los límites de cada agente son del motor de base de datos y no solo del prompt.

| Servidor | Rol de BD | Herramienta | Quién la usa |
|---|---|---|---|
| `sotica_obra` | `rol_avance` | `registrar_avance` | SUB-AVA |
| `sotica_obra` | `rol_avance` | `consultar_estado_obra` | ORQ-COST, SUB-AVA, SUB-DOC |
| `sotica_obra` | lectura | `consultar_presupuesto` | ORQ-COST, SUB-CM, SUB-AVA, SUB-DOC |
| `sotica_obra` | lectura | `leer_reporte_avance` | SUB-AVA (ORQ-COST **no** lee crudos) |
| `sotica_obra` | `rol_costos` | `registrar_computo` | SUB-CM |
| `sotica_obra` | lectura | `consultar_bloqueos` | ORQ-COST |
| `sotica_obra` | `rol_costos` | `resolver_bloqueo` | ORQ-COST (exige confirmación del usuario) |
| `sotica_docs` | lectura + `entregables` | `generar_excel_computos` | SUB-DOC |
| `sotica_planos` | — | `leer_plano_pdf` | SUB-CM — **fase 1.5, no implementada** |

Las **tres mínimas** que acordamos son `generar_excel_computos`, `registrar_avance` y
`consultar_estado_obra`. Las demás entraron porque sin ellas esas tres no cierran el ciclo:

- `consultar_presupuesto` y `leer_reporte_avance` son plomería de lectura: sin ellas nadie sabe
  contra qué medir ni qué interpretar.
- `consultar_bloqueos` y `resolver_bloqueo` son el flujo de resolución acordado: sin ellas un
  bloqueo se abre y nadie puede verlo ni cerrarlo.
- **`registrar_computo` es una adición nuestra al alcance mínimo**, y conviene saberlo: sin ella
  SUB-CM computa pero sus cantidades no llegan a la base, así que el Excel de SUB-DOC no reflejaría
  su trabajo y el ciclo no sería end-to-end. Escribe solo en el presupuesto **borrador**; marcar la
  base de control sigue siendo decisión humana desde el panel.

---

## 1. `registrar_avance` — servidor `sotica-obra`

Registra la interpretación estructurada de un reporte de campo, recalcula el estado consolidado y evalúa
desviaciones **en la misma transacción**. Solo SUB-AVA la tiene permitida.

```jsonc
// INPUT
{
  "proyecto_id": "uuid",
  "reporte_id": "uuid",                    // reporte crudo que se está interpretando
  "avances": [{
    "codigo_partida": "E-301",             // código interno o COVENIN del presupuesto BASE
    "fecha_avance": "2026-09-08",          // fecha del evento en obra, no la de subida
    "cantidad_periodo": 42.5,
    "unidad": "m3",                        // debe coincidir con la partida; si no, error duro
    "metodo": "medición en sitio con cinta, acta conjunta 2026-09-08",
    "etiqueta": "confirmado",              // confirmado | inferido | referencial | pendiente_confirmacion
    "confianza": "alto",                   // alto | medio | bajo
    "evidencia_archivo_ids": ["uuid"],
    "observacion": "..."
  }],
  "fecha_corte": "2026-09-08"
}
```

```jsonc
// OUTPUT
{
  "avances_registrados": 3,
  "estado_consolidado": { /* misma forma que consultar_estado_obra */ },
  "desviaciones_detectadas": [{
    "tipo": "atraso", "severidad": "alta", "codigo_partida": "E-301",
    "valor_plan": 68.0, "valor_real": 51.2, "brecha_pp": -16.8,
    "descripcion": "Concreto de fundaciones 16,8 pp por debajo del plan al 08/09/2026."
  }],
  "rechazos": [{
    "codigo_partida": "X-99",
    "motivo": "partida_no_presupuestada",
    "detalle": "El reporte describe trabajo que no existe en el presupuesto base. Posible obra extra: decide ORQ-COST con el usuario."
  }]
}
```

Comportamiento no negociable:

- **No toca `presupuestos` ni `partidas`.** El rol de BD no tiene ese permiso.
- Unidad distinta a la de la partida → error duro + desviación `inconsistencia_unidad`. No convierte sola.
- Avance sin `evidencia_archivo_ids` → se registra igual, pero abre desviación `sin_evidencia`.
  Nunca se descarta información en silencio.
- Recalcula desviación comparando acumulado real contra la curva de `planificacion_partida`
  (o interpolación lineal). **Siempre evalúa; nunca omite el cálculo por falta de umbral.**
- Marca el reporte crudo como `procesado`. El reporte en sí queda intacto (append-only).

## 2. `consultar_estado_obra` — servidor `sotica-obra`

Única fuente de verdad de ORQ-COST para responder "¿cómo va la obra?". No expone reportes crudos.

```jsonc
// INPUT
{ "proyecto_id": "uuid", "codigo_partida": null, "capitulo": null, "fecha_corte": null,
  "incluir_desviaciones": true }
```

```jsonc
// OUTPUT
{
  "proyecto": { "codigo": "SOT-2026-014", "nombre_obra": "...", "moneda": "USD" },
  "corte": "2026-09-10",
  "avance_fisico_real_pct": 51.2,
  "avance_fisico_plan_pct": 68.0,
  "desviacion_pp": -16.8,
  "avance_financiero_pct": 44.0,
  "monto_ejecutado": 812450.00,
  "monto_presupuestado": 1846000.00,

  // Estos tres campos vienen SIEMPRE. El prompt obliga a citarlos.
  "ultima_fecha_avance": "2026-08-29",
  "dias_sin_reporte": 12,
  "advertencia_datos": "Último avance registrado el 29/08/2026 (hace 12 días). No hay información posterior; el avance mostrado NO está proyectado al día de hoy.",

  "calidad_dato_global": "inferido",       // peor etiqueta presente en el acumulado
  "partidas_sin_avance": 14,
  "partidas": [{
    "codigo": "E-301", "descripcion": "Concreto f'c=250 en fundaciones", "unidad": "m3",
    "cantidad_presupuestada": 320.0, "cantidad_acumulada": 163.8,
    "pct_real": 51.2, "pct_plan": 68.0, "desviacion_pp": -16.8,
    "ultima_fecha_avance": "2026-08-29", "calidad_dato": "confirmado", "tiene_evidencia": true
  }],
  "desviaciones_abiertas": [ /* tipo, severidad, brecha, impacto_estimado */ ]
}
```

Si el proyecto **no tiene ningún avance registrado**, devuelve `ultima_fecha_avance: null` y
`advertencia_datos: "No hay avances cargados para esta obra. No es posible informar estado real."`
— nunca un 0 % silencioso ni el avance planificado disfrazado de real.

## 3. `generar_excel_computos` — servidor `sotica-docs`

Genera el libro de cómputos en formato SOTICA-CM-01, lo sube al bucket y lo registra en `entregables`.

```jsonc
// INPUT
{
  "proyecto_id": "uuid",
  "presupuesto_id": "uuid",
  "alcance": { "capitulos": ["Fundaciones"], "codigos_partida": null },
  "incluir": { "hojas_medicion": true, "resumen_por_capitulo": true,
               "lista_inconsistencias": true, "supuestos": true },
  "revision": "A"
}
```

```jsonc
// OUTPUT
{
  "archivo_id": "uuid",
  "codigo_documento": "SOTICA-CM-01",
  "revision": "A",
  "url_descarga": "https://.../SOTICA-CM-01_Rev-A.xlsx",
  "hojas": ["Portada","Índice de planos","Supuestos","Medición-Estructura","Resumen por capítulo","Inconsistencias"],
  "advertencias": ["Formato SOTICA propuesto — pendiente de ratificación (no hay plantilla oficial cargada)."]
}
```

Reglas de generación:

- Portada, código de documento, revisión, fecha, autoría y clasificación de confidencialidad, siempre.
- Fórmulas vivas (el subtotal de medición se calcula en la celda, no se escribe el número quemado).
- Cada cantidad muestra **etiqueta de dato y fuente** en columnas propias. Sin números sueltos sin origen.
- Hoja "Inconsistencias" con las cantidades no computables por falta de detalle. Si está vacía, se dice
  explícitamente que está vacía; no se omite la hoja.

## 4. `consultar_presupuesto` — servidor `sotica-obra` *(lectura, plomería)*

Devuelve el presupuesto base con partidas, unidades, cantidades, precios, etiquetas y fuentes.
Lectura pura. La usan ORQ-COST, SUB-CM, SUB-DOC y SUB-AVA para saber contra qué se mide.

## 5. `leer_reporte_avance` — servidor `sotica-obra` *(lectura, plomería)*

Devuelve el reporte crudo (texto, adjuntos, quién y cuándo) para que SUB-AVA lo interprete.
**Solo SUB-AVA la tiene permitida** — ORQ-COST no lee crudos.

---

## Fase 2 (no implementar ahora)

`generar_word_informe`, `generar_ppt`, `generar_gantt`, `registrar_valuacion`, `consultar_precios_civ`,
`checklist_pliego`, análisis FIDIC y exportación a multilaterales.
