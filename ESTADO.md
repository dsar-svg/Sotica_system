# Estado del proyecto SOTICA-COSTOS

**Última actualización:** 10 de septiembre de 2026
**Rama activa:** `openai-version` · **Rama anterior (Claude Agent SDK):** `anthropic-version`

Documento de traspaso. Si retomas el proyecto sin contexto previo, lee esto primero,
luego [ARQUITECTURA.md](ARQUITECTURA.md) y [README.md](README.md).

---

## 1. Qué es esto

Sistema multiagente de IA para ingeniería de costos de construcción en Venezuela, encargado por
**SOTICA**. Un orquestador (ORQ-COST) que dirige a subagentes especialistas, arma presupuestos,
cómputos y documentación en formato SOTICA, y lleva seguimiento de obra.

**Fuente de verdad del negocio:** `Solicitud_Agente_IA_Costos_SOTICA.pdf` v1.0 (sept. 2026), 14 páginas.
Está fuera del repo, en `C:\Users\pc\Documents\`. **Guarda una copia en un lugar estable.** Todas las
referencias tipo §2.3, §4.2, §5.1, §11 apuntan a ese documento.

Secciones que más se citan en el código y los prompts:

- **§2.3** matriz de delegación · **§4.1–4.7** los 7 subagentes oficiales
- **§5.1** contrato de briefing entre agentes · **§5.2** resolución de conflictos · **§5.3** trazabilidad
- **§7** formatos SOTICA · **§10.3** lo que SOTICA debe entregar · **§11** criterios de aceptación
- **§3.5** la regla transversal: el sistema no inventa; todo dato lleva etiqueta y fuente

---

## 2. Dónde vamos

**Ciclo 1 implementado y migrado a OpenAI Agents SDK.** Alcance: ORQ-COST + SUB-CM + SUB-DOC (solo
Excel) + SUB-AVA. Suficiente para probar la arquitectura de delegación end-to-end.

Dos hitos, en dos commits:

| Commit | Qué |
|---|---|
| `ccaf0c0` | Ciclo 1 completo sobre Claude Agent SDK |
| `e6554f8` | Migración de la capa de orquestación a OpenAI Agents SDK |

**Motivo de la migración:** solo hay crédito disponible en la API de OpenAI, no en la de Anthropic.
La base de datos, la lógica de negocio de los agentes y los contratos MCP **no se tocaron**.

### SUB-AVA no está en el documento original

El seguimiento de obra (subagente **SUB-AVA**, octavo agente) lo diseñamos nosotros a pedido del
cliente: el residente sube avances a demanda, SUB-AVA los interpreta contra el presupuesto base,
detecta desviaciones y actualiza el estado consolidado. **Nunca reescribe el presupuesto: lo cruza
contra él.** Si alguien de SOTICA busca esto en el PDF, no está ahí.

---

## 3. Decisiones cerradas (no reabrir sin motivo nuevo)

1. **No se usa n8n.** Orquestación con SDK de agentes, MCP como capa de herramientas, Postgres como estado.
2. **Delegación con agents-as-tools, no handoffs.** Un handoff transfiere la conversación y el control
   no vuelve, lo que rompería §2 (el usuario solo habla con el orquestador), §5.2 (ORQ-COST resuelve
   contradicciones) y §5.3 (paquete único). Se evaluó y se descartó explícitamente.
3. **MCP stdio real, no herramientas nativas del SDK.** El SDK de OpenAI no admite servidores
   in-process. Se montaron servidores MCP de verdad para que las herramientas sirvan a cualquier
   runtime. Fue la decisión correcta: sobrevivió al cambio de proveedor sin tocar contratos.
4. **Las reglas duras viven en el esquema, no solo en el prompt.** `CHECK` de `etiqueta_dato`, trigger
   de unidad, `reportes_avance` append-only, REVOKE por rol. Es lo único que no depende del modelo —
   por eso el cambio de SDK no las afectó.
5. **El presupuesto base es inmutable para el control de obra.** SUB-AVA no tiene permiso de escritura
   ni a nivel de base de datos.
6. **Los bloqueos solo los resuelve ORQ-COST con confirmación literal del usuario.** Sin resolución
   automática, sin rol de revisión aparte.
7. **`registrar_computo` fue una adición nuestra** al alcance mínimo de herramientas. Sin ella SUB-CM
   computa pero sus cantidades no llegan a la base y el ciclo no es end-to-end.

---

## 4. Qué está verificado y qué no

**Verificado con ejecución real:**

- `compileall` limpio sobre `backend` y `tests`.
- Handshake MCP stdio real: 8 herramientas publicadas, `required` intacto, enums de `etiqueta`,
  `confianza` y `decision` intactos, semántica `isError` preservada.
- Grafo de agentes: permisos por agente correctos, `output_type=RespuestaSubagente` en los tres
  subagentes, briefing §5.1 exigido como esquema requerido.
- El panel HTML se sirve (`GET /` → 200).
- Frontmatter de los 9 agentes parsea.

**NO verificado — pendiente:**

- **`db/schema.sql` nunca se ha ejecutado.** No hay Postgres ni Docker levantado en esta máquina.
  La primera corrida puede sacar errores de SQL.
- **Los criterios §11 nunca se han corrido** contra el modelo. Falta `OPENAI_API_KEY`.
- El ciclo de chat completo nunca se ha ejercitado.

---

## 5. Qué falta para arrancar

Dos bloqueantes, ninguno de código:

1. **Postgres corriendo.** Opciones: Docker, instalación nativa, o una base gestionada (Neon/Supabase)
   apuntada desde `SOTICA_DATABASE_URL`. Luego `db/schema.sql` y `db/seed/demo.sql`.
2. **`OPENAI_API_KEY` y decidir el modelo.** Hoy `SOTICA_MODEL=gpt-5` como default en
   `backend/core/config.py`. **Confirmar a qué modelo hay crédito.** Se cambia solo ahí; los nueve
   prompts no se tocan.

El venv del proyecto (`.venv/`) ya tiene todas las dependencias instaladas.

```bash
.venv/Scripts/python -m uvicorn backend.api.main:app --reload --port 8000
```

Con solo la clave de OpenAI, sin Postgres, ya se pueden correr los criterios §11:

```bash
.venv/Scripts/python -m tests.aceptacion_11
```

### Riesgo abierto que hay que cerrar antes de dar el ciclo 1 por bueno

**Los prompts fueron escritos y afinados contra un modelo Claude.** Lo estructural está cubierto por
la base de datos, pero reglas como *"no completes un reporte parcial con el rendimiento planificado"*
o *"declara el vacío en vez de rellenarlo"* viven solo en el prompt, y es el comportamiento que más
varía entre modelos. El cliente pidió explícitamente correr §11 —sobre todo §11.2 "no inventa"—
contra el modelo de OpenAI y reportar con ejemplos concretos si algún prompt se ablanda, **antes de
seguir construyendo**. Está pendiente.

---

## 6. Pendiente de ratificación por SOTICA

Nada de esto está decidido por el cliente; son propuestas técnicas nuestras, marcadas como tales en
el código y declaradas como supuesto en las salidas del sistema.

| Qué | Dónde vive | Propuesto |
|---|---|---|
| Umbrales de desviación | `config_control` (por proyecto / tipo de obra) | 5 / 10 / 20 pp |
| Días sin reporte para alerta | `config_control` | 15 días |
| Base de ponderación del avance físico | `config_control` + `fn_pct_fisico_obra()` | por monto de partida |
| Formatos de documento | `proyectos.formatos_ratificados` | juego propuesto §7.2 |

Diseñado para cargar valores distintos por tipo de obra **sin migración** — vialidad y edificación
probablemente necesiten umbrales distintos. `fn_pct_fisico_obra()` es el único lugar donde se pondera:
cambiar la base de ponderación el día que el cliente decida otra cosa es editar una función.

---

## 7. Conversación abierta con SOTICA: precios, partidas y licencias

**Este es el frente vivo del proyecto y es delicado.** El sistema hoy **no tiene catálogo de insumos ni
base de precios**: cada precio se escribe partida por partida con fuente obligatoria. Es la pata corta.

### Lo que hay que preguntarles (en este orden, como ingeniero, no como auditor)

1. *"¿Actualmente de dónde te guías con los precios para armar un presupuesto?"*
2. *"¿Y las partidas cómo las codifican — COVENIN, el pliego del ente, o códigos propios de la casa?"*
   (abierta a propósito: preguntar *"las tomas de COVENIN, ¿no?"* induce un "sí, claro" y no informa —
   y tapa justo lo que importa, porque **el catálogo de partidas suele venir dentro del mismo programa
   licenciado**, no de la norma)
3. *"¿Y eso lo tienen en el programa o en Excel?"* (revela el camino de exportación sin mencionar licencias)
4. Más adelante, cuando fluya: *"¿los rendimientos de dónde salen — de la Guía o de su experiencia en
   obra?"* Un APU con precios referenciales pero **rendimientos propios de SOTICA** vale mucho más que
   uno con ambos referenciales. Ese es su activo real.

Y pedirles lo que §10.3 ya pedía y nunca llegó: **un APU real y una lista de precios anonimizados**,
la lista de FCAS por tipo de cliente, y las partidas "de la casa".

### Cómo leer la respuesta

| Si dicen… | Significa | Acción |
|---|---|---|
| "Tenemos licencia de MaPreX / el Visor" | Mejor caso: licencia viva y camino de export | Pedir versión, fecha y formato de export |
| "Un Excel que armó el ingeniero X con precios de la Guía" | Datos derivados, copia de copia | Preguntar fecha y procedencia; licencia turbia |
| "Pedimos cotizaciones" | No hay Guía de por medio | Lo más limpio legalmente |
| "Copiamos de presupuestos anteriores nuestros" | Histórico propio | Suyo; la base más fácil y realista |
| "Un conocido nos pasa el visor" | Bandera roja | No ayudar a extenderlo; el sistema funciona sin eso |

En tres de los cinco escenarios **la Guía no hace falta**: cotizaciones e histórico propio bastan.

### Hechos técnicos que se pueden afirmar sin riesgo

1. El sistema **no contiene ni redistribuye** la base CIV–DataLaing. Hoy no hay catálogo de precios.
2. **No hay entrenamiento ni fine-tuning** con datos del cliente.
3. Si cargan su copia licenciada, **vive en la base de datos de SOTICA**, no se reutiliza con otros clientes.
4. **Pero los prompts viajan a la API de OpenAI.** Planos, pliegos y precios que entren al chat se
   transmiten a un tercero. **Esto hay que decirlo de frente**, porque el propio documento se compromete
   en §9 a proteger la confidencialidad del cliente. Mitigaciones: términos empresariales con retención
   cero, minimizar lo que entra al prompt (las herramientas devuelven solo las filas necesarias), y en
   el extremo un modelo autoalojado.

### Líneas que no se cruzan

- No afirmar que SOTICA tiene derecho a hacer X con la Guía: **eso lo define su convenio**.
- No ofrecer conseguir la base por otra vía si su licencia no permite exportar.
- No incorporar su base al producto ni reutilizarla con otro cliente.

> Nota útil: que el sistema **exija fuente y fecha en cada precio** es el mejor argumento en esta
> conversación. Un entregable donde cada número dice de dónde salió demuestra uso citado, que es lo
> contrario de una redistribución encubierta.

*(Quien escribe no es abogado; el convenio CIV–DataLaing firmado por SOTICA es el que manda.)*

---

## 8. Próximos pasos

**Inmediato**

1. Levantar Postgres y correr `schema.sql` + seed por primera vez.
2. Conseguir `OPENAI_API_KEY`, confirmar modelo, correr `tests/aceptacion_11.py`.
3. Reportar al cliente los §11 que fallen, con la salida textual. Reforzar prompts si hace falta.
4. Renombrar los precios del seed: hoy dicen `CIV-DataLaing ago-2026 (demo)` y **son inventados**;
   puede leerse como si fueran precios reales de la Guía. Cambiar a algo inequívoco.

**Fase 1.5**

- Catálogo versionado de precios: `insumos`, `bases_precio` (fuente, fecha, zona, moneda),
  `precios_insumo`. Una base como objeto citable, no una cadena de texto.
- `origen_precio` como enum en el esquema (`referencial_civ | cotizacion_proveedor | historico_sotica
  | oferta`), hoy solo vive en el prompt. Es lo que lo vuelve auditable, igual que `etiqueta_dato`.
- Herramientas MCP `importar_base_precios` (xlsx) y `consultar_precio_insumo(insumo, zona, fecha)`.
- `leer_plano_pdf` (servidor `sotica_planos`), hoy listado pero no implementado.

**Fase 2**

- `.pptx` y Word, FIDIC y organismos multilaterales.
- Activar SUB-ELE, SUB-HID, SUB-EST, SUB-VIA, SUB-SUE: ya están escritos y migrados al formato nuevo
  con `enabled: false`. Activarlos es quitar la bandera y sumarlos a `CICLO_1_AGENTES`.

---

## 9. Mapa del repo

```
ARQUITECTURA.md              decisiones de arquitectura, matriz de delegación, contrato §5.1
ESTADO.md                    este documento
README.md                    puesta en marcha y recorrido de prueba
db/schema.sql                esquema completo — NUNCA EJECUTADO TODAVÍA
db/seed/demo.sql             obra SOT-2026-014 con 5 partidas y planificación
backend/agents/*.md          los 9 system prompts. Una sola fuente; el código los carga
backend/core/agents.py       construcción de Agent + herramientas de delegación
backend/core/contratos.py    BriefingSOTICA y RespuestaSubagente (§5.1 tipado)
backend/core/orchestrator.py Runner + sesión persistente por obra
backend/core/control.py      aritmética de avance y desviaciones
backend/core/avance.py       registro de avance y flujo de bloqueos
backend/mcp/registry.py      registro de herramientas, independiente de SDK
backend/mcp/stdio_server.py  publica los registros como servidores MCP stdio
backend/mcp/fixtures.py      mismos contratos con datos enlatados, solo para §11
tests/aceptacion_11.py       criterios de aceptación del documento
frontend/index.html          chat + estado de obra + carga de evidencia + entregables
```

**Convención que conviene respetar:** los system prompts viven **solo** en `backend/agents/*.md`. El
código los carga, nunca los duplica en strings.
