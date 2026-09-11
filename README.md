# SOTICA-COSTOS — ciclo 1

ORQ-COST (Claude Agent SDK) + SUB-CM + SUB-DOC (Excel) + SUB-AVA, con MCP como capa de
herramientas y Postgres como estado. Arquitectura completa en [ARQUITECTURA.md](ARQUITECTURA.md);
contratos de herramientas en [backend/mcp/HERRAMIENTAS.md](backend/mcp/HERRAMIENTAS.md).

## Puesta en marcha

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env   # completar SOTICA_DATABASE_URL y ANTHROPIC_API_KEY
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

El panel queda en `http://localhost:8000`: chat con ORQ-COST, estado de obra, carga de
avances y archivos generados.

## Recorrido de prueba del ciclo 1

1. **Cómputo (ORQ-COST → SUB-CM).** «Computa las paredes de bloque de la planta baja: 45 m
   lineales por 2,80 m de altura, descontando 6 puertas de 0,90 × 2,10.» SUB-CM computa,
   persiste con `registrar_computo` en el presupuesto borrador y declara lo no computable.
2. **Excel (ORQ-COST → SUB-DOC).** «Genera el libro de cómputos.» Sale `SOTICA-CM-01_Rev-A_*.xlsx`
   con portada, control de revisiones, hojas de medición con fórmulas vivas e inconsistencias.
3. **Avance (panel → SUB-AVA).** Sube un reporte en «Cargar avance de obra»: texto libre + fotos.
   Luego, en el chat: «Procesa el último reporte de obra.»
4. **Consulta rápida (ORQ-COST solo).** «¿Cómo va la obra?» — responde desde el consolidado,
   citando la última fecha de avance. Si no hay avances, lo dice; no asume cronograma.
5. **Bloqueo.** Reporta avance en una partida que no existe («se vació la losa de tanquilla»):
   el avance queda retenido, ORQ-COST plantea la decisión y solo cierra el bloqueo con tu
   confirmación literal.

## Estado de verificación

- Python: `python -m compileall backend` pasa sin errores.
- Frontmatter de los 9 agentes: parsea correctamente.
- **`db/schema.sql` y `db/seed/demo.sql` no se han ejecutado todavía** — no hay Postgres ni
  Docker disponible en esta máquina. Primera ejecución real pendiente.
- El ciclo de chat no se ha corrido contra la API de Anthropic (falta `ANTHROPIC_API_KEY`).

## Pendiente de ratificación por SOTICA

| Qué | Dónde vive | Default propuesto |
|---|---|---|
| Umbrales de desviación | `config_control` (por proyecto / tipo de obra) | 5 / 10 / 20 pp |
| Días sin reporte para alerta | `config_control` | 15 días |
| Base de ponderación del avance físico | `config_control` + `fn_pct_fisico_obra` | por monto de partida |
| Formatos de documento | `proyectos.formatos_ratificados` | juego propuesto §7.2 |

Mientras `ratificado_por_sotica` sea `false`, toda salida que use esos valores los declara como
supuesto de la agencia, no como criterio del cliente.

## Fuera del ciclo 1

`.pptx`, Word, FIDIC/multilaterales, lectura automática de planos PDF (`sotica_planos`), y los
subagentes SUB-ELE / SUB-HID / SUB-EST / SUB-VIA / SUB-SUE — escritos en `backend/agents/` con
`enabled: false`; activarlos es quitar la bandera y sumarlos a `CICLO_1_AGENTES`.
