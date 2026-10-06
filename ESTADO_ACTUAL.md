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

- **Orquestación:** OpenAI Agents SDK. Los subagentes son herramientas de ORQ-COST (`delegar_sub_cm`,
  `delegar_sub_doc`, `delegar_sub_ava`), con contexto aislado y briefing tipado (§5.1).
- **Herramientas:** dos servidores MCP stdio (`sotica_obra`, `sotica_docs`) más un tercero de datos
  enlatados (`sotica_fixtures`) que solo usan las pruebas.
- **Datos:** PostgreSQL. Las reglas duras viven en el esquema (CHECK, triggers, funciones), no solo en
  los prompts.
- **Panel:** `frontend/index.html`, un solo archivo HTML/CSS/JS servido por FastAPI.
- **Prompts:** solo en `backend/agents/*.md`. El código los carga; no se duplican.

Agentes activos: **ORQ-COST, SUB-CM, SUB-DOC, SUB-AVA**. Los otros cinco (SUB-ELE, SUB-HID, SUB-EST,
SUB-VIA, SUB-SUE) tienen prompt escrito pero están apagados (`enabled: false`) y sin herramientas.

## 3. Qué funciona hoy

Todo lo de esta lista se ejecutó de verdad contra Postgres y `gpt-5`.

| Flujo | Estado |
|---|---|
| Cómputo por chat → SUB-CM lo registra en un presupuesto borrador con hoja de medición | Funciona |
| Libro de cómputos en Excel (SOTICA-CM-01) con fórmulas vivas | Funciona |
| APU con evidencia por insumo: origen, proveedor, enlace, fecha y quién lo cargó | Funciona |
| Cotización sin evidencia completa → pendiente de confirmar, fuera del total firme | Funciona; lo exige también la base de datos |
| Precios aproximados de materiales buscados en internet, con enlace y fecha | Funciona |
| Presupuesto en Excel (SOTICA-PRE-01): resumen, detalle, APU, indirectos, notas | Funciona; fórmulas verificadas abriéndolo en Excel |
| Reporte de campo → SUB-AVA → avance físico y financiero, desviaciones | Funciona |
| Trabajo no presupuestado → bloqueo que solo se cierra con decisión del usuario | Funciona |
| Bitácora de delegaciones con las herramientas que usó cada subagente | Funciona |
| Panel rediseñado: conversación + pestañas de avance, presupuesto, bloqueos, archivos, trazabilidad | Funciona |

**Criterios de aceptación §11:** 8 de 8 con `gpt-5` (`python -m tests.aceptacion_11`). Cubren los
criterios 1, 2, 3 y 7 del PDF; los criterios 4, 5, 6, 8 y 9 no tienen prueba.

**No usar `gpt-4o`:** en las pruebas inventó longitudes y diámetros de tubería e ignoró medidas dadas.

## 4. Sin verificar al cierre de esta sesión

Lo último que se tocó quedó a medias; revisarlo antes de confiar en ello.

- **Conservar el chat al recargar la página.** Se implementó con `sessionStorage`, pero la única prueba
  recargó a mitad de una respuesta y el hilo salió vacío. No se sabe si funciona en el caso normal.
- **Cerrar un bloqueo desde el panel nuevo.** La herramienta se llamó y la respuesta empezó a llegar,
  pero se interrumpió antes de comprobar que el contador de la pestaña bajara a cero. Por API sí está
  verificado.
- **Diseño en pantalla angosta.** Se corrigió el desborde horizontal y el encabezado; solo se revisó
  la pantalla inicial.
- **Carga de fotos en un reporte.** Los archivos se guardan, pero nunca se probó con adjuntos reales.
- `scripts/db_stop.ps1` no se ha ejecutado nunca.

## 5. Lo que la propuesta promete y todavía no existe

Es la brecha contra lo vendido. Conviene decidir qué entra en la demo y qué se declara como siguiente fase.

1. **Cinco especialistas apagados** (eléctrico, hidráulico, estructural, vialidad, suelos). El criterio
   §11.1 del cliente pide una orden mixta con dictámenes de al menos cuatro subagentes: hoy es imposible.
2. **Word, PowerPoint y Gantt.** Solo se genera Excel.
3. **Lectura de planos en PDF.** No existe; el panel ni siquiera permite subir un plano.
4. **Interpretación de fotos.** Al modelo solo le llega el nombre del archivo, no la imagen.
5. **Indirectos, utilidad, impuestos y FCAS.** El presupuesto es costo directo; esos valores esperan
   datos de SOTICA y no se suponen.
6. **Usuarios y contraseñas**, y una forma de **crear una obra** desde el panel (hoy solo por SQL).
7. **Despliegue** en el servidor del cliente: no hay Dockerfile ni configuración.
8. **Costos de API medidos.** La propuesta estima 1–4 USD por presupuesto; nunca se midió. Además ahora
   hay búsqueda web, que suma costo.

## 6. Próximos pasos, en orden

1. Verificar los cinco puntos de la sección 4.
2. Ensayar el guion completo de `docs/GUION_DEMO.md` de principio a fin, desde el panel.
3. Actualizar `README.md`, `ARQUITECTURA.md` y `backend/mcp/HERRAMIENTAS.md`: no mencionan
   `registrar_apu`, `generar_excel_presupuesto`, la búsqueda web ni los scripts nuevos.
4. Medir el costo real de API de un recorrido completo.
5. Decidir con el cliente el alcance de la demo frente a la sección 5, y acordar por escrito qué
   significa "entrega funcional".
6. Construir lo que falte de la sección 5, empezando por lo que el cliente priorice.

## 7. Decisiones tomadas en esta sesión

- **Se sigue con OpenAI.** Se portó la orquestación a Claude Agent SDK como respaldo (rama `claude-sdk`),
  pero no se llegó a ejecutar contra el modelo y la propuesta enviada nombra a OpenAI.
- **La etiqueta de dato de un precio la asigna el sistema** según la evidencia, no el modelo.
- **Precios de internet:** permitidos solo para materiales, siempre con enlace y fecha, marcados como
  referenciales. Mano de obra y rendimientos los da una persona. Se apaga con `SOTICA_BUSCAR_PRECIOS=0`.
- **El FCAS no se supone** y los **indirectos no se calculan** hasta que SOTICA los defina.
- **El avance físico pondera sobre todo el presupuesto base.** Antes promediaba solo las partidas con
  avance y sobrestimaba (45,42 % en vez de 11,93 %).
- **Los cómputos nuevos van a un presupuesto borrador**; el presupuesto base de control no se toca.
- **Los precios de la obra demo son ficticios** y ya no citan a CIV-DataLaing.
- Los consumos de material por unidad que no dé el usuario (por ejemplo, bloques por m²) los infiere el
  modelo y los declara como supuesto. Conviene que un ingeniero de SOTICA los revise.

## 8. Puesta en marcha en otra PC (Windows)

Lo que **no** viaja en el repo: `.env` (clave de OpenAI), `.pgdata/` (la base), `storage/` (archivos
generados), `.venv/`, el PDF de especificación y la propuesta.

1. **Requisitos:** Python 3.14, PostgreSQL 17 y Git. Excel para abrir los entregables.
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

Si PostgreSQL quedó en otra ruta, ajustarla en `scripts/db_start.ps1` y `scripts/db_stop.ps1`.
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
backend/api/main.py          API HTTP y chat
frontend/index.html          el panel
scripts/                     reset_demo, db_start, db_stop, demo_start
tests/aceptacion_11.py       criterios de aceptación contra el modelo
```
