# Estado actual — SOTICA-COSTOS

**Fecha:** 6 de octubre de 2026 · **Rama de trabajo:** `openai-version`

Documento para retomar el proyecto en otra máquina. Reemplaza a `ESTADO.md` (10 de septiembre), que
quedó desactualizado y solo sirve como historia de decisiones.

---

## 1. Qué es el proyecto

Sistema multiagente de ingeniería de costos de construcción para **SOTICA** (Venezuela). Un orquestador
(ORQ-COST) conversa con el usuario y delega en especialistas; el sistema produce cómputos, análisis de
precios unitarios, presupuesto y control de avance de obra en formato SOTICA.

- **Especificación del cliente:** `Solicitud_Agente_IA_Costos_SOTICA.pdf` v1.0 (14 páginas). **No está en
  el repo.** Las referencias tipo §2.3, §5.1, §11 del código apuntan a ese PDF.
- **Propuesta comercial ya enviada al cliente:** `Propuesta_SOTICA-COSTOS-1.docx`. **Tampoco está en el
  repo.** Precio cerrado de 3.000 USD (40 % anticipo, 60 % contra entrega funcional), con 2 años de
  servidor y 100 USD de API incluidos. Nombra a OpenAI y GPT-5 como proveedor y modelo.
- **Objetivo inmediato:** dejar el sistema listo para una demostración al cliente.

Hay que copiar ambos documentos a la otra PC a mano.

## 2. Arquitectura en una mirada

- **Orquestación:** OpenAI Agents SDK. Los subagentes son herramientas de ORQ-COST (`delegar_sub_cm`, `delegar_sub_hid`,
  etc.), con contexto aislado y briefing tipado (§5.1).
- **Herramientas:** tres servidores MCP stdio (`sotica_obra`, `sotica_docs`, `sotica_planos`) más uno de datos
  enlatados (`sotica_fixtures`) que solo usan las pruebas.
- **Datos:** PostgreSQL. Las reglas duras viven en el esquema (CHECK, triggers, funciones), no solo en
  los prompts.
- **Panel:** `frontend/index.html`, un solo archivo HTML/CSS/JS servido por FastAPI.
- **Prompts:** solo en `backend/agents/*.md`. El código los carga; no se duplican.

Agentes activos: los **nueve** (ORQ-COST + SUB-CM, SUB-DOC, SUB-AVA, SUB-ELE, SUB-HID, SUB-EST,
SUB-VIA, SUB-SUE). Se apagan con `enabled: false` en su archivo de prompt.

## 3. Qué funciona hoy

| Flujo | Estado |
|---|---|
| Cómputo por chat → SUB-CM lo registra en un presupuesto borrador con hoja de medición | Funciona |
| **La aritmética del cómputo la hace el sistema**: `registrar_computo` evalúa cada expresión y corrige al modelo | Funciona (`tests/aritmetica_computo.py`) |
| Planos PDF: el panel los sube, SUB-CM y especialistas los leen con `listar_planos` / `leer_plano_pdf` (texto, sin OCR) | Funciona contra la base (`tests/smoke_planos.py`) |
| Libro de cómputos SOTICA-CM-01 con fórmulas vivas | Funciona |
| APU con evidencia por insumo; cotización sin evidencia → pendiente, fuera del total firme | Funciona; lo exige también la base |
| Precios aproximados de materiales buscados en internet, con enlace y fecha | Funciona |
| Presupuesto SOTICA-PRE-01 con **precio de oferta**: administración, utilidad e IVA con `registrar_indirectos` (solo con cita del usuario o pliego) | Funciona; verificado en Excel |
| **Cronograma SOTICA-PLA-01**: Gantt por semanas, coherencia contra rendimientos (NETWORKDAYS), curva S, premisas, hitos | Funciona; verificado en Excel |
| **Word** en formato SOTICA: informe de avance (INF-01), técnico (INF-02), propuesta (COM-01), memoria (MEM-01), dictamen (DIC-01), observaciones al pliego (OBS-01) | Funciona; secciones obligatorias faltantes salen PENDIENTE |
| **PowerPoint** SOTICA-PRS-01 | Funciona |
| Orden mixta repartida entre especialistas (§11.1) | Funciona con 5 especialistas en la prueba |
| FIDIC + pliego: declara qué manda (§11.8) | Funciona |
| Reporte de campo → SUB-AVA → avance físico y financiero, desviaciones, bloqueos | Funciona |
| Panel: conversación, pestañas, **alta de obra** con memoria de proyecto, carga de planos | Funciona |

**Criterios de aceptación §11:** 12 de 12 con `gpt-5` (`python -m tests.aceptacion_11`, ~0,75 USD por
corrida, medido). En la última corrida 11.8 falló una vez por no escribir "desviación"; con el prompt
reforzado pasó 3 de 3. Cubren los criterios 1, 2, 3, 4, 5, 7 y 8 del PDF; 6 y 9 no tienen prueba automática.

**Modelo:** `gpt-5`. Se midieron `gpt-5-mini`, `gpt-5.4-mini` y `gpt-5.6-luna`: fallan en "no inventa"
o en aritmética. Opción probada para producción: `SOTICA_MODEL_SUBAGENTES=gpt-5-mini` (orquestador
en `gpt-5`) pasó 8/8 dos veces con ~28 % menos costo. **No usar `gpt-4o`.**

**OpenAI no atiende desde Venezuela** (`unsupported_country_region_territory`): la demo necesita VPN o
un servidor fuera del país. `python -m scripts.verificar_demo` lo comprueba.

## 4. Verificación del 6/10/2026

Recorrido completo del guion (9 órdenes) contra el panel, la base real y `gpt-5`, sin errores
(`tmp/recorrido.py`, fuera de git). Verificado en esa corrida y en el navegador:

- Chat conservado al recargar la página (respuesta completa).
- Cerrar un bloqueo desde el chat: el panel queda en 0 y el avance en 11,93 % real vs 31,92 % plan.
- Pantalla angosta (375 px): sin desborde horizontal en las cinco pestañas.
- Plano A-02 subido desde el panel y computado por ejes: 149,64 m², sin pisar la planta baja.
- `scripts/db_start.ps1` y `db_stop.ps1` ejecutados (Postgres 18.6 de scoop).

Sin verificar: carga de fotos reales en un reporte de campo (los archivos se guardan; el modelo solo
recibe el nombre).

## 5. Lo que la propuesta promete y todavía no existe

1. **PDF de los entregables.** Se exportan a mano desde Excel, Word o PowerPoint.
2. **Planos:** solo texto del PDF; sin OCR ni lectura del dibujo. Un escaneo no se puede leer.
3. **Interpretación de fotos.** Al modelo solo le llega el nombre del archivo, no la imagen.
4. **FCAS, administración, utilidad e impuestos** solo se aplican si SOTICA o el pliego los dan.
5. **Los especialistas no persisten sus propias cantidades**: devuelven dictamen (queda en la bitácora)
   y SUB-CM registra cómputos.
6. **Usuarios y contraseñas.**
7. **Despliegue** en el servidor del cliente: no hay Dockerfile ni configuración (y tiene que estar
   fuera de Venezuela o con salida por VPN, por OpenAI).
8. **Valuaciones y fórmula polinómica** (§3.2, caso 6.3.6): no hay herramienta; ORQ-COST solo razona.

## 6. Próximos pasos, en orden

1. Ensayar `docs/GUION_DEMO.md` en el panel con la VPN de la demo.
2. Actualizar `README.md` y `ARQUITECTURA.md` con lo de esta sesión.
3. Decidir con el cliente el alcance frente a la sección 5 y qué significa "entrega funcional".

## 7. Decisiones tomadas en esta sesión

- **Se sigue con OpenAI.** Se portó la orquestación a Claude Agent SDK como respaldo (rama `claude-sdk`),
  pero no se llegó a ejecutar contra el modelo y la propuesta enviada nombra a OpenAI.
- **La etiqueta de dato de un precio la asigna el sistema** según la evidencia, no el modelo.
- **Precios de internet:** permitidos solo para materiales, siempre con enlace y fecha, marcados como
  referenciales. Mano de obra y rendimientos los da una persona. Se apaga con `SOTICA_BUSCAR_PRECIOS=0`.
- **El FCAS y los indirectos no se suponen**: se aplican solo con cita del usuario o del pliego.
- **Se queda `gpt-5`** (6/10/2026) por fiabilidad frente al cliente; la propuesta lo nombra.
- **El avance físico pondera sobre todo el presupuesto base.** Antes promediaba solo las partidas con
  avance y sobrestimaba (45,42 % en vez de 11,93 %).
- **Los cómputos nuevos van a un presupuesto borrador**; el presupuesto base de control no se toca.
- **Los precios de la obra demo son ficticios** y ya no citan a CIV-DataLaing.
- Los consumos de material por unidad que no dé el usuario (por ejemplo, bloques por m²) los infiere el
  modelo y los declara como supuesto. Conviene que un ingeniero de SOTICA los revise.

## 8. Puesta en marcha en otra PC (Windows)

Lo que **no** viaja en el repo: `.env` (clave de OpenAI), `.pgdata/` (la base), `storage/` (archivos
generados), `.venv/`, el PDF de especificación y la propuesta.

1. **Requisitos:** Python 3.14, PostgreSQL 17 o 18 y Git. Excel para abrir los entregables.
2. **Clonar y preparar el entorno:**

   ```powershell
   git clone https://github.com/dsar-svg/Sotica_system.git
   cd Sotica_system
   git checkout openai-version
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. **Crear la base local del proyecto** (instancia propia en `.pgdata`, puerto 5433; no usa ni necesita
   la clave del Postgres instalado). Pide una contraseña para el usuario `sotica`; usar `sotica`, que
   es el valor de desarrollo de `.env.example`:

   ```powershell
   & "C:\Program Files\PostgreSQL\17\bin\initdb.exe" -D .pgdata -U sotica -W --auth=scram-sha-256 --encoding=UTF8 --locale=C
   .\scripts\db_start.ps1
   & "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U sotica -h 127.0.0.1 -p 5433 sotica
   ```

4. **Configurar `.env`:** copiar `.env.example` a `.env` y dejar:

   ```
   SOTICA_DATABASE_URL=postgresql://sotica:sotica@localhost:5433/sotica
   SOTICA_MODEL=gpt-5
   OPENAI_API_KEY=<tu clave>
   ```

   La clave va **solo** en `.env`, nunca en `.env.example`, que sí se sube a git.
5. **Cargar el esquema y la obra demo** (borra todo lo que haya en esa base):

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.reset_demo
   ```

6. **Arrancar** y abrir <http://localhost:8000>:

   ```powershell
   .\scripts\demo_start.ps1
   ```

`scripts/db_start.ps1` y `scripts/db_stop.ps1` usan el `pg_ctl` del PATH (por ejemplo, Postgres de
scoop) y, si no hay, `C:\Program Files\PostgreSQL\17\bin`. Probado también con PostgreSQL 18.6.
El Postgres del proyecto no arranca solo al reiniciar la PC: `demo_start.ps1` lo levanta.

## 9. Ramas

| Rama | Contenido |
|---|---|
| `openai-version` | **La de trabajo.** Todo lo descrito aquí. |
| `claude-sdk` | Respaldo de la orquestación sobre Claude Agent SDK. Compila; nunca se ejecutó contra el modelo. |
| `anthropic-version` | Versión original de septiembre sobre Claude Agent SDK. Histórica. |

## 10. Mapa rápido del repo

```
ESTADO_ACTUAL.md             este documento
docs/GUION_DEMO.md           recorrido de la demo, paso a paso, y qué decir en cada uno
PRODUCT.md                   contexto de diseño del panel
db/schema.sql                esquema completo, con las reglas duras
db/seed/demo.sql             obra SOT-2026-014 (precios ficticios)
backend/agents/*.md          los 9 prompts
backend/core/agents.py       construcción de agentes, delegación y bitácora
backend/core/apu.py          APU con evidencia y reglas de etiquetado
backend/core/computo.py      registro de cómputos en el borrador
backend/core/control.py      aritmética de avance y desviaciones
backend/core/avance.py       registro de avance y bloqueos
backend/mcp/sotica_obra.py   herramientas de presupuesto, APU, avance y bloqueos
backend/mcp/sotica_docs.py   generadores de Excel
backend/mcp/sotica_planos.py listar_planos y leer_plano_pdf (SUB-CM)
backend/api/main.py          API HTTP y chat
frontend/index.html          el panel
scripts/                     reset_demo, db_start, db_stop, demo_start
tests/aceptacion_11.py       criterios de aceptación contra el modelo
```
