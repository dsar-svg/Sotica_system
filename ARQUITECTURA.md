# SOTICA-COSTOS — Arquitectura del sistema multiagente

Sistema: **SOTICA-IA-COST-VE-001**
Base: Claude Agent SDK (orquestador + subagentes nativos) + servidores MCP como capa de herramientas + Postgres + bucket de archivos.

> Fuente de verdad funcional: `Solicitud_Agente_IA_Costos_SOTICA.pdf` v1.0 (sept. 2026).
> Este documento define **cómo** se construye; el PDF define **qué** debe hacer.

---

## 1. Decisiones de arquitectura (cerradas)

| Capa | Decisión |
|---|---|
| Orquestador | ORQ-COST = agente principal del Claude Agent SDK. Único interlocutor del usuario. |
| Subagentes | 8 subagentes nativos del SDK (7 del documento + SUB-AVA), cada uno con system prompt propio, herramientas permitidas y contexto aislado. |
| Herramientas | Servidores MCP. **MCP es la capa de herramientas, nunca el orquestador.** |
| Persistencia | Postgres (proyecto, presupuesto, partidas, avances, estado consolidado, trazabilidad). |
| Archivos | Bucket (S3/MinIO) para planos, fotos de obra, PDFs y entregables generados. |
| Frontend | Chat web simple + panel de archivos generados + carga de evidencia de obra. |
| Fuera de alcance fase 1 | .pptx, FIDIC/multilaterales, SUB-ELE/HID/EST/VIA/SUE activos. |

**Ciclo funcional 1 (end-to-end de delegación):**
`ORQ-COST + SUB-CM + SUB-DOC (solo Excel) + SUB-AVA`

Los otros 5 subagentes quedan escritos y registrados, pero **deshabilitados** en la configuración del ciclo 1
(`enabled: false` en el registro de agentes), para que activarlos sea un cambio de bandera, no de arquitectura.

---

## 2. Estructura de carpetas

```
Sotica_system/
├── ARQUITECTURA.md                  # este documento
├── db/
│   ├── schema.sql                   # esquema Postgres completo (fase 1)
│   └── seed/                        # catálogos: capítulos COVENIN, unidades, plantillas FCAS
├── backend/
│   ├── core/
│   │   ├── agent_registry.*         # carga de los .md como subagentes del SDK
│   │   ├── orchestrator.*           # arranque de ORQ-COST, sesión por proyecto
│   │   ├── session_memory.*         # memoria de proyecto (moneda, ente, FCAS, formatos)
│   │   └── db.*                     # acceso Postgres
│   ├── agents/                      # SYSTEM PROMPTS — una fuente por agente
│   │   ├── orq-cost.md              # redactado aquí
│   │   ├── sub-ava.md               # redactado aquí (nuevo, no está en el PDF)
│   │   ├── sub-cm.md                # casi textual §4.2
│   │   ├── sub-doc.md               # casi textual §4.1
│   │   ├── sub-ele.md               # casi textual §4.3   (fase 2)
│   │   ├── sub-hid.md               # casi textual §4.4   (fase 2)
│   │   ├── sub-est.md               # casi textual §4.5   (fase 2)
│   │   ├── sub-via.md               # casi textual §4.6   (fase 2)
│   │   └── sub-sue.md               # casi textual §4.7   (fase 2)
│   ├── mcp/
│   │   ├── HERRAMIENTAS.md          # contratos de las herramientas MCP
│   │   ├── sotica-obra/             # registrar_avance, consultar_estado_obra, consultar_presupuesto
│   │   ├── sotica-docs/             # generar_excel_computos (xlsx). docx/pptx = fase 2
│   │   └── sotica-planos/           # lectura de PDF de planos (fase 1.5)
│   └── api/                         # HTTP: chat SSE, upload evidencia, listado de entregables
├── frontend/
│   └── src/                         # chat + panel de archivos + formulario de avance
└── docs/
    └── formatos/                    # plantillas SOTICA §7 (portada, control de revisiones, etc.)
```

**Regla de una sola fuente:** el system prompt de cada agente vive **solo** en `backend/agents/*.md`.
El código los carga; nunca los duplica en strings.

---

## 3. Mapa de agentes y matriz de delegación (§2.3)

| Código | Rol | Herramientas MCP permitidas | Ciclo 1 |
|---|---|---|---|
| ORQ-COST | Orquestador, presupuesto, APU, integración | `consultar_presupuesto`, `consultar_estado_obra`, delegación a subagentes | Sí |
| SUB-CM | Cómputos métricos | `leer_plano_pdf` (1.5), `consultar_presupuesto` | Sí |
| SUB-DOC | Documentación / Excel | `generar_excel_computos`, `consultar_presupuesto`, `consultar_estado_obra` | Sí (solo xlsx) |
| SUB-AVA | Seguimiento y control de avance | `leer_reporte_avance`, `registrar_avance`, `consultar_presupuesto`, `consultar_estado_obra` | Sí |
| SUB-ELE / HID / EST / VIA / SUE | Especialidades | según §4.3–4.7 | No — fase 2 |

Enrutamiento (§2.3), implementado como reglas dentro del prompt de ORQ-COST + posibilidad de forzar
especialista desde el chat (`@SUB-CM ...`):

- Medir / cuantificar / leer planos generales → **SUB-CM** (+ SUB-HID o SUB-ELE si el plano es de red o eléctrico)
- Eléctrico → **SUB-ELE** · Acueductos y cloacas → **SUB-HID** · Estructural → **SUB-EST**
- Vialidad → **SUB-VIA** · Suelos/geotecnia → **SUB-SUE**
- Cronograma, Gantt, informes, propuestas, archivos de oficina → **SUB-DOC**
- **Avance de obra, evidencia, desviaciones, "¿cómo va la obra?" → SUB-AVA** *(adición nuestra)*
- APU, presupuesto, FCAS, valuación, fórmula polinómica, pliego, estrategia → **ORQ-COST**

**Contrato interno de delegación (§5.1)** — el briefing viaja como JSON y se persiste en `delegaciones`:

```jsonc
{
  "codigo_proyecto": "SOT-2026-014", "nombre_obra": "...",
  "producto_solicitado": "...",            // pregunta o producto exacto
  "documentos_disponibles": ["archivo_id..."],
  "norma_rectora": "COVENIN 2000-II",
  "unidades": "SI", "moneda": "USD", "fecha_base": "2026-09-01",
  "prohibido_inferir": ["diámetros no dibujados", "cargas eléctricas"],
  "formato_respuesta": "cantidades | criterio | riesgos | preguntas al usuario"
}
```

Y toda respuesta de subagente devuelve: `resultado, método, supuestos, fuentes, nivel_confianza (alto|medio|bajo), bloqueos`.

---

## 4. Regla transversal de etiquetado (§3.5) — se aplica en la BD, no solo en el prompt

Todo número que entra al sistema lleva `etiqueta_dato` **NOT NULL**:

| Etiqueta | Significado |
|---|---|
| `confirmado` | Está en plano, pliego, estudio, valuación firmada o instrucción del usuario. |
| `inferido` | Deducido con criterio de ingeniería; se explica el método. |
| `referencial` | CIV-DataLaing, COVENIN, catálogo o experiencia; con fuente y fecha. |
| `pendiente_confirmacion` | Vacío crítico; se detiene esa línea y se declara el impacto. |

El esquema **rechaza** cantidades sin etiqueta y sin `fuente`. Es la garantía estructural del criterio de
aceptación 11.2 ("no inventa"): no depende de que el modelo se porte bien.

---

## 5. Seguimiento de obra (función nueva, no está en el PDF)

Flujo:

```
Residente/inspector --(chat o formulario)--> reportes_avance   (CRUDO, inmutable)
                                                   |
                                            SUB-AVA interpreta
                                                   |
                                   avances_partida (ESTRUCTURADO, append-only)
                                                   |
                                      recálculo determinístico
                                                   v
                             estado_obra / estado_obra_partida / desviaciones
                                                   |
                           ORQ-COST lee SOLO el consolidado <--- "¿cómo va la obra?"
                                                   |
                                   informe formal --> SUB-DOC (Word/PPT, fase 2)
```

Invariantes:

1. **SUB-AVA nunca escribe en `presupuestos` ni en `partidas`.** Permiso denegado a nivel de rol de BD.
   El presupuesto base es inmutable; el avance se *cruza* contra él.
2. `reportes_avance` es append-only: el texto/foto original del residente nunca se edita ni se borra.
   Una corrección es un reporte nuevo que anula al anterior (`anula_reporte_id`).
3. **Detección de desviación obligatoria**: al registrar avance se compara real vs. planificado a esa fecha
   (interpolación sobre `planificacion_partida`) y se abre fila en `desviaciones` si supera el umbral.
   No se calla ninguna.
4. **Regla del dato viejo**: toda respuesta sobre estado de obra incluye `ultima_fecha_avance` y
   `dias_sin_reporte`. Si no hay avances recientes, el sistema lo dice
   ("último avance registrado el [fecha]"); **está prohibido asumir que la obra sigue el cronograma**.
   `consultar_estado_obra` devuelve siempre esos campos — el prompt no puede omitirlos porque la
   herramienta los entrega y el prompt obliga a citarlos.
5. ORQ-COST **no relee reportes crudos** para consultas de chat. Solo `consultar_estado_obra`.
   Los crudos son territorio de SUB-AVA.

Cadencia: **a demanda**, sin periodicidad fija. El sistema no infiere avance por paso del tiempo.

---

## 6. Trazabilidad (§5.3)

La tabla `delegaciones` alimenta directamente el anexo "Quién hizo qué" de todo paquete final:
qué agente recibió qué briefing, qué devolvió, con qué nivel de confianza y en qué momento.
No es logging opcional: es un entregable contractual.
