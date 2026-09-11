# SOTICA-COSTOS — ciclo 1

> **¿Retomas el proyecto sin contexto?** Empieza por [ESTADO.md](ESTADO.md): dónde vamos, qué está
> verificado, qué falta para arrancar y la conversación abierta con SOTICA sobre precios y licencias.

ORQ-COST (**OpenAI Agents SDK**) + SUB-CM + SUB-DOC (Excel) + SUB-AVA, con **MCP stdio** como capa de
herramientas y Postgres como estado. Arquitectura completa en [ARQUITECTURA.md](ARQUITECTURA.md);
contratos de herramientas en [backend/mcp/HERRAMIENTAS.md](backend/mcp/HERRAMIENTAS.md).

> Migrado desde Claude Agent SDK. La base de datos, la lógica de negocio de los agentes y los
> contratos MCP no cambiaron; cambió la capa de orquestación.

## Puesta en marcha

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env   # completar SOTICA_DATABASE_URL y OPENAI_API_KEY
```

Base de datos (Postgres 14+):

```bash
psql "$SOTICA_DATABASE_URL" -f db/schema.sql
psql "$SOTICA_DATABASE_URL" -f db/seed/demo.sql
```

Servidor:

```bash
uvicorn backend.api.main:app --reload --port 8000
```

El panel queda en `http://localhost:8000`. Los servidores MCP se lanzan solos como subprocesos; para
inspeccionarlos a mano:

```bash
python -m backend.mcp.stdio_server sotica_obra
```

## Delegación: agents-as-tools, no handoffs

ORQ-COST invoca a cada subagente como herramienta (`delegar_sub_cm`, `delegar_sub_doc`,
`delegar_sub_ava`). El run del subagente es anidado y sin sesión compartida: ve su briefing, no la
conversación del usuario.

Se descartó `handoffs` a propósito: un handoff transfiere la conversación y el control no vuelve, lo
que rompería §2 (el usuario solo habla con el orquestador), §5.2 (ORQ-COST resuelve contradicciones
entre especialistas) y §5.3 (paquete único con anexo de trazabilidad).

El contrato de §5.1 vive en [`backend/core/contratos.py`](backend/core/contratos.py) como esquema
tipado: `BriefingSOTICA` de ida (todos los campos requeridos) y `RespuestaSubagente` de vuelta
(`nivel_confianza` obligatorio). Antes era prosa; ahora lo valida el SDK.

## Criterios de aceptación §11

```bash
python -m tests.aceptacion_11          # todos
python -m tests.aceptacion_11 11.2     # solo "no inventa"
```

Corre contra el modelo real usando un servidor MCP de fixtures con **los mismos JSON Schema** que
producción, así que mide comportamiento del agente (¿delega?, ¿inventa?, ¿declara el vacío?) sin
depender de Postgres. No sustituye a las pruebas de base de datos.

## Estado de verificación

- `compileall` limpio sobre backend y tests.
- **Servidores MCP verificados por handshake stdio real**: 8 herramientas publicadas, enums de
  `etiqueta`/`confianza`/`decision` y `required` intactos, semántica `isError` preservada.
- Grafo de agentes verificado: permisos por agente correctos, `output_type=RespuestaSubagente` en los
  tres subagentes, briefing §5.1 exigido como esquema requerido.
- **`db/schema.sql` y el seed siguen sin ejecutarse** — no hay Postgres ni Docker en esta máquina.
- **Los criterios §11 siguen sin correrse** — falta `OPENAI_API_KEY`.

## Pendiente de ratificación por SOTICA

| Qué | Dónde vive | Default propuesto |
|---|---|---|
| Umbrales de desviación | `config_control` (por proyecto / tipo de obra) | 5 / 10 / 20 pp |
| Días sin reporte para alerta | `config_control` | 15 días |
| Base de ponderación del avance físico | `config_control` + `fn_pct_fisico_obra` | por monto de partida |
| Formatos de documento | `proyectos.formatos_ratificados` | juego propuesto §7.2 |

## Fuera del ciclo 1

`.pptx`, Word, FIDIC/multilaterales, lectura automática de planos PDF (`sotica_planos`), y los
subagentes SUB-ELE / SUB-HID / SUB-EST / SUB-VIA / SUB-SUE — ya migrados al formato nuevo y con
`enabled: false`; activarlos es quitar la bandera y sumarlos a `CICLO_1_AGENTES`.
