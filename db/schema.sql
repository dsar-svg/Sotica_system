-- =====================================================================
-- SOTICA-COSTOS  |  SOTICA-IA-COST-VE-001
-- Esquema Postgres — Ciclo 1 (ORQ-COST + SUB-CM + SUB-DOC + SUB-AVA)
--
-- Principio estructural: ningun numero entra sin etiqueta de dato y sin
-- fuente. La regla "el sistema no inventa" (PDF 3.5 y 11.2) se hace
-- cumplir en el esquema, no solo en el prompt.
--
-- PENDIENTE DE RATIFICACION POR SOTICA (mismo patron que los formatos
-- de la seccion 7 del documento): los umbrales de desviacion y la base
-- de ponderacion del avance fisico. Ambos viven en config_control,
-- son configurables por proyecto y por tipo de obra, y no estan
-- quemados en ningun CHECK ni en ninguna query.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------
-- Tipos
-- ---------------------------------------------------------------------

-- Escala de certeza del PDF 3.5. Obligatoria en toda cantidad/precio/avance.
CREATE TYPE etiqueta_dato AS ENUM (
  'confirmado',              -- plano, pliego, estudio, valuacion, instruccion del usuario
  'inferido',                -- deducido con criterio de ingenieria (exige metodo)
  'referencial',             -- CIV-DataLaing, COVENIN, catalogo (exige fuente + fecha)
  'pendiente_confirmacion'   -- vacio critico declarado, con impacto estimado
);

CREATE TYPE nivel_confianza AS ENUM ('alto', 'medio', 'bajo');

CREATE TYPE codigo_agente AS ENUM (
  'ORQ-COST','SUB-DOC','SUB-CM','SUB-ELE','SUB-HID',
  'SUB-EST','SUB-VIA','SUB-SUE','SUB-AVA','HUMANO'
);

CREATE TYPE tipo_presupuesto AS ENUM ('oficial', 'oferente', 'ejecucion');
CREATE TYPE estado_presupuesto AS ENUM ('borrador', 'aprobado', 'superado');

CREATE TYPE tipo_archivo AS ENUM (
  'plano','pliego','memoria','especificacion','estudio_suelos','topografia',
  'presupuesto_previo','cotizacion','foto_obra','valuacion','minuta',
  'plantilla_sotica','entregable','otro'
);

CREATE TYPE tipo_insumo AS ENUM ('material','equipo','mano_obra','subcontrato','transporte','herramienta');

CREATE TYPE estado_reporte AS ENUM ('pendiente','procesado','rechazado','anulado');

CREATE TYPE tipo_desviacion AS ENUM (
  'atraso',                  -- real < plan a la fecha
  'adelanto',                -- real > plan a la fecha (tambien se reporta)
  'sobre_ejecucion',         -- acumulado > cantidad presupuestada
  'sin_evidencia',           -- avance declarado sin foto/valuacion/medicion
  'sin_reporte',             -- obra sin avances cargados hace N dias
  'inconsistencia_unidad',   -- el reporte usa unidad distinta a la partida
  'partida_no_presupuestada' -- se reporta trabajo que no existe en el presupuesto base
);

CREATE TYPE severidad AS ENUM ('informativa','media','alta','critica');
CREATE TYPE estado_desviacion AS ENUM ('abierta','reconocida','cerrada');

-- Bloqueos: lo que el sistema NO resuelve solo y necesita decision humana.
CREATE TYPE tipo_bloqueo AS ENUM (
  'partida_no_presupuestada',
  'inconsistencia_unidad',
  'cantidad_no_cuantificable',
  'contradiccion_evidencia',
  'otro'
);
CREATE TYPE estado_bloqueo AS ENUM ('abierto','resuelto','descartado');
CREATE TYPE decision_bloqueo AS ENUM (
  'mapear_a_partida',        -- era una partida existente mal nombrada por el residente
  'diferir_a_obra_extra',    -- es trabajo fuera del presupuesto base: lo decide ORQ-COST + usuario
  'descartar'                -- el reporte no procede (error, duplicado, mal atribuido)
);
CREATE TYPE estado_espera AS ENUM ('en_espera','promovido','diferido','descartado');

-- Base de ponderacion del avance fisico. PENDIENTE DE RATIFICACION.
CREATE TYPE base_ponderacion AS ENUM ('monto','cantidad','horas_hombre');

-- Ambito de una fila de configuracion; resuelve por precedencia.
CREATE TYPE ambito_config AS ENUM ('global','tipo_obra','proyecto');

-- ---------------------------------------------------------------------
-- 1. Proyectos / obras
-- ---------------------------------------------------------------------

CREATE TABLE proyectos (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  codigo              text UNIQUE NOT NULL,            -- SOT-2026-014
  nombre_obra         text NOT NULL,
  cliente             text,                            -- CVC, PDVSA, MPPT, gobernacion, privado...
  tipo_ente           text,                            -- publico_nacional | estadal | municipal | privado | multilateral
  -- Determina que fila de config_control aplica cuando no hay una propia del proyecto.
  tipo_obra           text NOT NULL DEFAULT 'edificacion',  -- edificacion | vialidad | hidraulica | electrificacion | industrial
  ubicacion           text,
  zona_precios        text,                            -- zonificacion MaPreX / DataLaing
  -- Memoria de proyecto (PDF 10.1): estas decisiones no se re-preguntan cada sesion.
  moneda_base         text NOT NULL DEFAULT 'USD' CHECK (moneda_base IN ('VES','USD')),
  moneda_secundaria   text CHECK (moneda_secundaria IN ('VES','USD')),
  fecha_base_precios  date NOT NULL,
  plantilla_fcas      text,                            -- edificacion | vialidad | PDVSA/PEQUIVEN | ...
  norma_rectora       text,                            -- COVENIN 2000-II, pliego X, FIDIC Red Book...
  formatos_ratificados boolean NOT NULL DEFAULT false, -- false => SUB-DOC usa el juego propuesto (PDF 7.2)
  fecha_inicio_contractual date,
  fecha_fin_contractual    date,
  estado              text NOT NULL DEFAULT 'activo',
  creado_en           timestamptz NOT NULL DEFAULT now(),
  CHECK (moneda_secundaria IS NULL OR moneda_secundaria <> moneda_base)
);

-- ---------------------------------------------------------------------
-- 2. Configuracion de control  — PENDIENTE DE RATIFICACION POR SOTICA
-- ---------------------------------------------------------------------
-- Precedencia: proyecto > tipo_obra > global. Cargar un juego distinto
-- para vialidad, o para una obra puntual, es un INSERT — no una migracion.

CREATE TABLE config_control (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ambito                ambito_config NOT NULL,
  tipo_obra             text,                          -- solo si ambito='tipo_obra'
  proyecto_id           uuid REFERENCES proyectos(id) ON DELETE CASCADE,  -- solo si ambito='proyecto'

  -- (a) Umbrales de desviacion, en puntos porcentuales de avance fisico.
  umbral_media_pp       numeric(6,2) NOT NULL,
  umbral_alta_pp        numeric(6,2) NOT NULL,
  umbral_critica_pp     numeric(6,2) NOT NULL,
  -- Dias sin reporte a partir de los cuales se levanta desviacion 'sin_reporte'.
  dias_sin_reporte_alerta int NOT NULL,

  -- (b) Base de ponderacion del avance fisico consolidado.
  base_ponderacion      base_ponderacion NOT NULL DEFAULT 'monto',

  -- Trazabilidad del estado de ratificacion. Mientras sea false, toda salida
  -- que use estos valores debe declararlos como supuesto no ratificado.
  ratificado_por_sotica boolean NOT NULL DEFAULT false,
  ratificado_en         date,
  ratificado_por        text,
  nota                  text,
  actualizado_en        timestamptz NOT NULL DEFAULT now(),

  CHECK (umbral_media_pp > 0 AND umbral_alta_pp > umbral_media_pp AND umbral_critica_pp > umbral_alta_pp),
  CHECK (dias_sin_reporte_alerta > 0),
  CHECK (
    (ambito = 'global'    AND tipo_obra IS NULL     AND proyecto_id IS NULL) OR
    (ambito = 'tipo_obra' AND tipo_obra IS NOT NULL AND proyecto_id IS NULL) OR
    (ambito = 'proyecto'  AND tipo_obra IS NULL     AND proyecto_id IS NOT NULL)
  ),
  CHECK (ratificado_por_sotica = false OR (ratificado_en IS NOT NULL AND ratificado_por IS NOT NULL))
);

CREATE UNIQUE INDEX config_control_global   ON config_control ((true)) WHERE ambito = 'global';
CREATE UNIQUE INDEX config_control_tipo     ON config_control (tipo_obra) WHERE ambito = 'tipo_obra';
CREATE UNIQUE INDEX config_control_proyecto ON config_control (proyecto_id) WHERE ambito = 'proyecto';

-- Valores de arranque: propuesta tecnica, NO ratificada.
INSERT INTO config_control (ambito, umbral_media_pp, umbral_alta_pp, umbral_critica_pp,
                            dias_sin_reporte_alerta, base_ponderacion, ratificado_por_sotica, nota)
VALUES ('global', 5, 10, 20, 15, 'monto', false,
        'Propuesta tecnica de la agencia. PENDIENTE DE RATIFICACION POR SOTICA: '
        'umbrales 5/10/20 pp y ponderacion por monto de partida (estandar de valuacion venezolana). '
        'Vialidad y edificacion probablemente requieran umbrales distintos; cargar filas de '
        'ambito=tipo_obra cuando el cliente los defina.');

-- Resolucion de configuracion: un solo lugar. Toda la logica la llama.
CREATE OR REPLACE FUNCTION fn_config_control(p_proyecto uuid)
RETURNS config_control AS $$
  SELECT c.*
    FROM config_control c
    JOIN proyectos p ON p.id = p_proyecto
   WHERE (c.ambito = 'proyecto'  AND c.proyecto_id = p.id)
      OR (c.ambito = 'tipo_obra' AND c.tipo_obra   = p.tipo_obra)
      OR (c.ambito = 'global')
   ORDER BY CASE c.ambito WHEN 'proyecto' THEN 1 WHEN 'tipo_obra' THEN 2 ELSE 3 END
   LIMIT 1;
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------
-- 3. Archivos / evidencia  (metadata; el binario vive en el bucket)
-- ---------------------------------------------------------------------

CREATE TABLE archivos (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id     uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  tipo            tipo_archivo NOT NULL,
  nombre          text NOT NULL,
  storage_key     text NOT NULL UNIQUE,                -- <proyecto>/<uuid>.<ext>
  mime            text NOT NULL,
  bytes           bigint NOT NULL CHECK (bytes > 0),
  sha256          text NOT NULL,                       -- deduplicacion + integridad de evidencia
  subido_por      text NOT NULL,                       -- usuario humano o codigo de agente
  capturado_en    timestamptz,                         -- fecha real de captura de la foto
  geo             jsonb,
  metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
  creado_en       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON archivos (proyecto_id, tipo);

-- ---------------------------------------------------------------------
-- 4. Presupuesto y partidas  (BASE INMUTABLE para el seguimiento)
-- ---------------------------------------------------------------------

CREATE TABLE presupuestos (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id     uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  version         int  NOT NULL,
  tipo            tipo_presupuesto NOT NULL,           -- PDF 3.3: oficial / oferente / ejecucion
  estado          estado_presupuesto NOT NULL DEFAULT 'borrador',
  es_base_control boolean NOT NULL DEFAULT false,      -- unico contra el que se mide el avance
  moneda          text NOT NULL,
  fecha_base      date NOT NULL,
  clase_estimado  text,                                -- AACE clase 5..1 (PDF 8.2)
  creado_por      codigo_agente NOT NULL DEFAULT 'ORQ-COST',
  creado_en       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (proyecto_id, version)
);
CREATE UNIQUE INDEX presupuesto_base_unico
  ON presupuestos (proyecto_id) WHERE es_base_control;

CREATE TABLE partidas (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  presupuesto_id   uuid NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
  proyecto_id      uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  codigo_covenin   text,
  codigo_interno   text NOT NULL,                      -- estable en computo/APU/presupuesto/Gantt/valuacion
  capitulo         text NOT NULL,
  subcapitulo      text,
  descripcion      text NOT NULL,
  unidad           text NOT NULL,                      -- m, m2, m3, kg, pza, glb
  cantidad         numeric(18,4) NOT NULL CHECK (cantidad >= 0),
  precio_unitario  numeric(18,4) CHECK (precio_unitario >= 0),
  monto            numeric(18,2) GENERATED ALWAYS AS (cantidad * COALESCE(precio_unitario,0)) STORED,
  especialidad     text,
  etiqueta_cantidad etiqueta_dato NOT NULL,
  fuente_cantidad   text NOT NULL,
  etiqueta_precio   etiqueta_dato,
  fuente_precio     text,
  agente_responsable codigo_agente NOT NULL,
  orden            int NOT NULL DEFAULT 0,
  creado_en        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (presupuesto_id, codigo_interno),
  CHECK ( (precio_unitario IS NULL) OR (etiqueta_precio IS NOT NULL AND fuente_precio IS NOT NULL) )
);
CREATE INDEX ON partidas (proyecto_id, capitulo);

CREATE TABLE apu_renglones (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  partida_id     uuid NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
  tipo           tipo_insumo NOT NULL,
  descripcion    text NOT NULL,
  unidad         text NOT NULL,
  cantidad       numeric(18,6) NOT NULL,
  rendimiento    numeric(18,6),
  desperdicio_pct numeric(6,3) DEFAULT 0,
  precio_unitario numeric(18,4) NOT NULL,
  etiqueta       etiqueta_dato NOT NULL,
  fuente         text NOT NULL,
  fecha_fuente   date
);

CREATE TABLE mediciones (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  partida_id     uuid NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
  archivo_id     uuid REFERENCES archivos(id),
  referencia     text NOT NULL,                        -- "Plano E-02, corte B-B, eje 4, cota +3.60"
  expresion      text NOT NULL,                        -- "2 x (4.20 x 0.30 x 0.60)"
  subtotal       numeric(18,4) NOT NULL,
  unidad         text NOT NULL,
  etiqueta       etiqueta_dato NOT NULL,
  observacion    text,
  agente         codigo_agente NOT NULL DEFAULT 'SUB-CM',
  creado_en      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE faltantes (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id    uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  ambito         text NOT NULL,
  descripcion    text NOT NULL,
  impacto_estimado text,
  como_obtenerlo text NOT NULL,
  agente         codigo_agente NOT NULL,
  estado         text NOT NULL DEFAULT 'abierto',
  creado_en      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 5. Planificacion (base de comparacion del avance)
-- ---------------------------------------------------------------------

CREATE TABLE planificacion_partida (
  partida_id     uuid PRIMARY KEY REFERENCES partidas(id) ON DELETE CASCADE,
  proyecto_id    uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  fecha_inicio   date NOT NULL,
  fecha_fin      date NOT NULL,
  cantidad_plan  numeric(18,4) NOT NULL,
  -- [{"fecha":"2026-10-15","pct":25.0}, ...]  NULL => interpolacion lineal
  curva          jsonb,
  rendimiento_declarado text,
  origen         codigo_agente NOT NULL DEFAULT 'SUB-DOC',
  CHECK (fecha_fin >= fecha_inicio)
);

-- ---------------------------------------------------------------------
-- 6. Seguimiento de obra — SUB-AVA
-- ---------------------------------------------------------------------

CREATE TABLE reportes_avance (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id      uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  reportado_por    text NOT NULL,
  fecha_reporte    date NOT NULL,                      -- fecha del EVENTO en obra
  recibido_en      timestamptz NOT NULL DEFAULT now(),
  canal            text NOT NULL DEFAULT 'chat',
  texto_libre      text,
  estado           estado_reporte NOT NULL DEFAULT 'pendiente',
  procesado_en     timestamptz,
  procesado_por    codigo_agente,
  nota_procesamiento text,
  anula_reporte_id uuid REFERENCES reportes_avance(id),
  CHECK (estado <> 'procesado' OR procesado_en IS NOT NULL)
);
CREATE INDEX ON reportes_avance (proyecto_id, fecha_reporte DESC);
CREATE INDEX ON reportes_avance (estado) WHERE estado = 'pendiente';

CREATE TABLE reporte_adjuntos (
  reporte_id  uuid NOT NULL REFERENCES reportes_avance(id) ON DELETE CASCADE,
  archivo_id  uuid NOT NULL REFERENCES archivos(id),
  rol         text NOT NULL,                           -- foto | valuacion | medicion | acta | otro
  PRIMARY KEY (reporte_id, archivo_id)
);

CREATE TABLE avances_partida (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reporte_id          uuid NOT NULL REFERENCES reportes_avance(id) ON DELETE CASCADE,
  proyecto_id         uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  partida_id          uuid NOT NULL REFERENCES partidas(id),
  fecha_avance        date NOT NULL,
  cantidad_periodo    numeric(18,4) NOT NULL CHECK (cantidad_periodo >= 0),
  unidad              text NOT NULL,
  metodo              text NOT NULL,
  etiqueta            etiqueta_dato NOT NULL,          -- foto sola => 'inferido', jamas 'confirmado'
  confianza           nivel_confianza NOT NULL,
  observacion         text,
  interpretado_por    codigo_agente NOT NULL DEFAULT 'SUB-AVA',
  creado_en           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON avances_partida (proyecto_id, fecha_avance DESC);
CREATE INDEX ON avances_partida (partida_id, fecha_avance DESC);

CREATE TABLE avance_evidencia (
  avance_id   uuid NOT NULL REFERENCES avances_partida(id) ON DELETE CASCADE,
  archivo_id  uuid NOT NULL REFERENCES archivos(id),
  PRIMARY KEY (avance_id, archivo_id)
);

CREATE TABLE estado_obra_partida (
  partida_id            uuid PRIMARY KEY REFERENCES partidas(id) ON DELETE CASCADE,
  proyecto_id           uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  cantidad_acumulada    numeric(18,4) NOT NULL DEFAULT 0,
  cantidad_presupuestada numeric(18,4) NOT NULL,
  pct_fisico_real       numeric(6,2)  NOT NULL DEFAULT 0,
  pct_fisico_plan       numeric(6,2),
  desviacion_pp         numeric(6,2),
  monto_ejecutado       numeric(18,2) NOT NULL DEFAULT 0,
  ultima_fecha_avance   date,                          -- NULL = nunca se reporto nada
  ultimo_avance_id      uuid REFERENCES avances_partida(id),
  calidad_dato          etiqueta_dato,                 -- peor etiqueta del acumulado
  tiene_evidencia       boolean NOT NULL DEFAULT false,
  actualizado_en        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON estado_obra_partida (proyecto_id);

CREATE TABLE estado_obra (
  proyecto_id           uuid PRIMARY KEY REFERENCES proyectos(id) ON DELETE CASCADE,
  presupuesto_base_id   uuid NOT NULL REFERENCES presupuestos(id),
  pct_fisico_real       numeric(6,2) NOT NULL DEFAULT 0,
  pct_fisico_plan       numeric(6,2),
  pct_financiero        numeric(6,2) NOT NULL DEFAULT 0,
  monto_ejecutado       numeric(18,2) NOT NULL DEFAULT 0,
  monto_presupuestado   numeric(18,2) NOT NULL,
  ultima_fecha_avance   date,
  dias_sin_reporte      int,
  partidas_sin_avance   int NOT NULL DEFAULT 0,
  desviaciones_abiertas int NOT NULL DEFAULT 0,
  bloqueos_abiertos     int NOT NULL DEFAULT 0,
  avances_en_espera     int NOT NULL DEFAULT 0,
  -- Copia de la config vigente al momento del calculo, para que el informe
  -- pueda declarar con que umbrales y que ponderacion se produjo el numero.
  base_ponderacion_usada base_ponderacion,
  config_ratificada     boolean NOT NULL DEFAULT false,
  fecha_corte           date NOT NULL,
  actualizado_en        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE desviaciones (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id    uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  partida_id     uuid REFERENCES partidas(id),
  avance_id      uuid REFERENCES avances_partida(id),
  tipo           tipo_desviacion NOT NULL,
  severidad      severidad NOT NULL,
  valor_plan     numeric(18,4),
  valor_real     numeric(18,4),
  brecha         numeric(18,4),
  descripcion    text NOT NULL,
  impacto_estimado text,
  detectada_por  codigo_agente NOT NULL DEFAULT 'SUB-AVA',
  detectada_en   timestamptz NOT NULL DEFAULT now(),
  estado         estado_desviacion NOT NULL DEFAULT 'abierta',
  cerrada_en     timestamptz,
  nota_cierre    text
);
CREATE INDEX ON desviaciones (proyecto_id, estado, severidad);

-- ---------------------------------------------------------------------
-- 7. Bloqueos y avances en espera  (flujo de resolucion)
-- ---------------------------------------------------------------------
-- Quien abre:    SUB-AVA (y cualquier subagente, via ORQ-COST).
-- Quien resuelve: SOLO ORQ-COST, y solo con confirmacion explicita del
--                 usuario en el chat. No hay resolucion automatica ni rol
--                 de revision aparte en el ciclo 1.
-- Mientras el bloqueo este abierto, el avance asociado queda en
-- avances_en_espera: cuenta como pendiente_confirmacion y NO entra al
-- consolidado. La cascada es explicita, no silenciosa.

CREATE TABLE bloqueos (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id       uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  reporte_id        uuid REFERENCES reportes_avance(id) ON DELETE CASCADE,
  tipo              tipo_bloqueo NOT NULL,
  descripcion       text NOT NULL,
  datos             jsonb NOT NULL DEFAULT '{}'::jsonb,  -- payload original del avance rechazado
  abierto_por       codigo_agente NOT NULL DEFAULT 'SUB-AVA',
  abierto_en        timestamptz NOT NULL DEFAULT now(),
  estado            estado_bloqueo NOT NULL DEFAULT 'abierto',
  decision          decision_bloqueo,
  resolucion        text,
  -- Texto literal de la confirmacion del usuario en el chat. Sin esto no se resuelve.
  confirmacion_usuario text,
  resuelto_por      codigo_agente,
  resuelto_en       timestamptz,
  CHECK (estado = 'abierto' OR (decision IS NOT NULL
                                AND confirmacion_usuario IS NOT NULL
                                AND resuelto_por IS NOT NULL
                                AND resuelto_en IS NOT NULL))
);
CREATE INDEX ON bloqueos (proyecto_id, estado);

CREATE TABLE avances_en_espera (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bloqueo_id       uuid NOT NULL REFERENCES bloqueos(id) ON DELETE CASCADE,
  proyecto_id      uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  reporte_id       uuid NOT NULL REFERENCES reportes_avance(id) ON DELETE CASCADE,
  codigo_partida_reportado text NOT NULL,              -- tal como lo dijo el residente; SIN FK a proposito
  fecha_avance     date NOT NULL,
  cantidad_periodo numeric(18,4) NOT NULL,
  unidad           text NOT NULL,
  metodo           text NOT NULL,
  etiqueta         etiqueta_dato NOT NULL DEFAULT 'pendiente_confirmacion',
  confianza        nivel_confianza NOT NULL,
  observacion      text,
  evidencia_ids    uuid[] NOT NULL DEFAULT '{}',
  estado           estado_espera NOT NULL DEFAULT 'en_espera',
  promovido_a      uuid REFERENCES avances_partida(id),
  creado_en        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON avances_en_espera (proyecto_id, estado);

-- Vista de bandeja: lo que nadie ha resuelto todavia, por obra.
CREATE VIEW v_bloqueos_abiertos AS
SELECT b.id            AS bloqueo_id,
       p.codigo        AS codigo_proyecto,
       p.nombre_obra,
       b.proyecto_id,
       b.tipo,
       b.descripcion,
       b.abierto_por,
       b.abierto_en,
       (now()::date - b.abierto_en::date)              AS dias_abierto,
       count(e.id) FILTER (WHERE e.estado = 'en_espera') AS avances_retenidos,
       r.fecha_reporte,
       r.reportado_por
  FROM bloqueos b
  JOIN proyectos p ON p.id = b.proyecto_id
  LEFT JOIN reportes_avance r  ON r.id = b.reporte_id
  LEFT JOIN avances_en_espera e ON e.bloqueo_id = b.id
 WHERE b.estado = 'abierto'
 GROUP BY b.id, p.codigo, p.nombre_obra, r.fecha_reporte, r.reportado_por
 ORDER BY b.abierto_en;

-- ---------------------------------------------------------------------
-- 8. Trazabilidad, supuestos y entregables
-- ---------------------------------------------------------------------

CREATE TABLE delegaciones (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id    uuid REFERENCES proyectos(id) ON DELETE CASCADE,
  sesion_id      text,
  agente_origen  codigo_agente NOT NULL,
  agente_destino codigo_agente NOT NULL,
  briefing       jsonb NOT NULL,
  respuesta      jsonb,
  confianza      nivel_confianza,
  iniciada_en    timestamptz NOT NULL DEFAULT now(),
  finalizada_en  timestamptz
);
CREATE INDEX ON delegaciones (proyecto_id, iniciada_en DESC);

CREATE TABLE supuestos (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id    uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  ambito         text NOT NULL,
  texto          text NOT NULL,
  etiqueta       etiqueta_dato NOT NULL,
  fuente         text,
  impacto_estimado text,
  agente         codigo_agente NOT NULL,
  estado         text NOT NULL DEFAULT 'vigente',
  creado_en      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE entregables (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proyecto_id       uuid NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
  archivo_id        uuid NOT NULL REFERENCES archivos(id),
  codigo_documento  text NOT NULL,
  revision          text NOT NULL DEFAULT 'A',
  titulo            text NOT NULL,
  formato           text NOT NULL CHECK (formato IN ('xlsx','docx','pdf','pptx')),
  generado_por      codigo_agente NOT NULL,
  formato_oficial   boolean NOT NULL DEFAULT false,
  creado_en         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (proyecto_id, codigo_documento, revision)
);

-- ---------------------------------------------------------------------
-- 9. Calculo del avance  — UN SOLO LUGAR
-- ---------------------------------------------------------------------
-- (b) La base de ponderacion del avance fisico se decide aqui y solo aqui.
-- Cambiarla el dia que SOTICA ratifique otra cosa = editar fn_pct_fisico_obra.
-- Ninguna query de la aplicacion pondera por su cuenta.

-- % planificado de UNA partida a una fecha: curva si existe, lineal si no.
CREATE OR REPLACE FUNCTION fn_pct_plan_partida(p_partida uuid, p_fecha date)
RETURNS numeric AS $$
DECLARE
  pl planificacion_partida;
  pct numeric;
BEGIN
  SELECT * INTO pl FROM planificacion_partida WHERE partida_id = p_partida;
  IF NOT FOUND THEN
    RETURN NULL;                                   -- sin plan no se inventa un plan
  END IF;

  IF p_fecha <= pl.fecha_inicio THEN RETURN 0; END IF;
  IF p_fecha >= pl.fecha_fin    THEN RETURN 100; END IF;

  IF pl.curva IS NOT NULL THEN
    SELECT (elem->>'pct')::numeric INTO pct
      FROM jsonb_array_elements(pl.curva) elem
     WHERE (elem->>'fecha')::date <= p_fecha
     ORDER BY (elem->>'fecha')::date DESC
     LIMIT 1;
    RETURN COALESCE(pct, 0);
  END IF;

  RETURN round(
    100.0 * (p_fecha - pl.fecha_inicio)::numeric
          / NULLIF((pl.fecha_fin - pl.fecha_inicio), 0)::numeric, 2);
END $$ LANGUAGE plpgsql STABLE;

-- % fisico REAL consolidado de la obra. Unica implementacion de la ponderacion.
CREATE OR REPLACE FUNCTION fn_pct_fisico_obra(p_proyecto uuid)
RETURNS numeric AS $$
DECLARE
  cfg config_control;
  resultado numeric;
BEGIN
  cfg := fn_config_control(p_proyecto);

  IF cfg.base_ponderacion = 'monto' THEN
    -- Default: ponderado por monto de partida (estandar de valuacion venezolana).
    -- PENDIENTE DE RATIFICACION POR SOTICA.
    SELECT CASE WHEN COALESCE(sum(pa.monto), 0) = 0 THEN 0
                ELSE round(sum(eop.pct_fisico_real * pa.monto) / sum(pa.monto), 2) END
      INTO resultado
      FROM estado_obra_partida eop
      JOIN partidas pa ON pa.id = eop.partida_id
     WHERE eop.proyecto_id = p_proyecto;

  ELSIF cfg.base_ponderacion = 'cantidad' THEN
    -- Alternativa: proporcion de cantidad ejecutada sobre cantidad presupuestada.
    -- Solo es defendible si las partidas comparten unidad; se ofrece porque el
    -- cliente puede pedirla, no porque la recomendemos.
    SELECT CASE WHEN COALESCE(sum(eop.cantidad_presupuestada), 0) = 0 THEN 0
                ELSE round(100.0 * sum(eop.cantidad_acumulada)
                                 / sum(eop.cantidad_presupuestada), 2) END
      INTO resultado
      FROM estado_obra_partida eop
     WHERE eop.proyecto_id = p_proyecto;

  ELSE
    RAISE EXCEPTION
      'base_ponderacion=% no implementada. Requiere cargar horas-hombre por partida en el APU antes de habilitarla.',
      cfg.base_ponderacion;
  END IF;

  RETURN COALESCE(resultado, 0);
END $$ LANGUAGE plpgsql STABLE;

-- % fisico PLANIFICADO de la obra, con la misma base de ponderacion.
CREATE OR REPLACE FUNCTION fn_pct_plan_obra(p_proyecto uuid, p_fecha date)
RETURNS numeric AS $$
DECLARE
  cfg config_control;
  resultado numeric;
BEGIN
  cfg := fn_config_control(p_proyecto);

  IF cfg.base_ponderacion = 'monto' THEN
    SELECT CASE WHEN COALESCE(sum(pa.monto), 0) = 0 THEN NULL
                ELSE round(sum(fn_pct_plan_partida(pa.id, p_fecha) * pa.monto)
                           / sum(pa.monto), 2) END
      INTO resultado
      FROM partidas pa
      JOIN planificacion_partida pl ON pl.partida_id = pa.id
     WHERE pa.proyecto_id = p_proyecto;
  ELSE
    SELECT CASE WHEN COALESCE(sum(pl.cantidad_plan), 0) = 0 THEN NULL
                ELSE round(sum(fn_pct_plan_partida(pa.id, p_fecha) * pl.cantidad_plan)
                           / sum(pl.cantidad_plan), 2) END
      INTO resultado
      FROM partidas pa
      JOIN planificacion_partida pl ON pl.partida_id = pa.id
     WHERE pa.proyecto_id = p_proyecto;
  END IF;

  RETURN resultado;   -- NULL si la obra no tiene planificacion cargada
END $$ LANGUAGE plpgsql STABLE;

-- Severidad de una desviacion segun los umbrales VIGENTES del proyecto.
CREATE OR REPLACE FUNCTION fn_severidad_desviacion(p_proyecto uuid, p_brecha_pp numeric)
RETURNS severidad AS $$
DECLARE
  cfg config_control;
  b numeric := abs(COALESCE(p_brecha_pp, 0));
BEGIN
  cfg := fn_config_control(p_proyecto);
  IF b >= cfg.umbral_critica_pp THEN RETURN 'critica';
  ELSIF b >= cfg.umbral_alta_pp THEN RETURN 'alta';
  ELSIF b >= cfg.umbral_media_pp THEN RETURN 'media';
  ELSE RETURN 'informativa';
  END IF;
END $$ LANGUAGE plpgsql STABLE;

-- ---------------------------------------------------------------------
-- 10. Guardas duras
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION chk_unidad_avance() RETURNS trigger AS $$
DECLARE u text;
BEGIN
  SELECT unidad INTO u FROM partidas WHERE id = NEW.partida_id;
  IF u IS DISTINCT FROM NEW.unidad THEN
    RAISE EXCEPTION 'Unidad de avance (%) no coincide con la partida (%).', NEW.unidad, u;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_unidad_avance BEFORE INSERT ON avances_partida
  FOR EACH ROW EXECUTE FUNCTION chk_unidad_avance();

CREATE OR REPLACE FUNCTION chk_reporte_inmutable() RETURNS trigger AS $$
BEGIN
  IF NEW.texto_libre    IS DISTINCT FROM OLD.texto_libre
     OR NEW.fecha_reporte  IS DISTINCT FROM OLD.fecha_reporte
     OR NEW.reportado_por  IS DISTINCT FROM OLD.reportado_por THEN
    RAISE EXCEPTION 'reportes_avance es append-only: una correccion es un reporte nuevo con anula_reporte_id.';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reporte_inmutable BEFORE UPDATE ON reportes_avance
  FOR EACH ROW EXECUTE FUNCTION chk_reporte_inmutable();

-- ---------------------------------------------------------------------
-- 11. Roles: SUB-AVA no puede tocar el presupuesto base
-- ---------------------------------------------------------------------
-- El servidor MCP sotica-obra se conecta con rol_avance; el de costos con rol_costos.
-- Descomentar al desplegar con usuarios separados.
--
-- CREATE ROLE rol_avance LOGIN;
-- GRANT SELECT ON presupuestos, partidas, planificacion_partida, config_control TO rol_avance;
-- GRANT SELECT, INSERT ON reportes_avance, avances_partida, avance_evidencia,
--                          desviaciones, bloqueos, avances_en_espera TO rol_avance;
-- GRANT SELECT, INSERT, UPDATE ON estado_obra, estado_obra_partida TO rol_avance;
-- REVOKE INSERT, UPDATE, DELETE ON presupuestos, partidas FROM rol_avance;
