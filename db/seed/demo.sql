-- Obra de prueba para ejercitar el ciclo 1 end-to-end.
-- Cantidades y precios ficticios; sirven para probar delegación, no para presupuestar.

INSERT INTO proyectos (codigo, nombre_obra, cliente, tipo_ente, tipo_obra, ubicacion,
                       zona_precios, moneda_base, fecha_base_precios, plantilla_fcas,
                       norma_rectora, formatos_ratificados,
                       fecha_inicio_contractual, fecha_fin_contractual)
VALUES ('SOT-2026-014', 'Edificio administrativo — sede regional', 'Gobernación (demo)',
        'publico_estadal', 'edificacion', 'Barquisimeto, Lara', 'Centro-occidente',
        'USD', DATE '2026-08-01', 'edificacion', 'COVENIN 2000-II', false,
        DATE '2026-09-01', DATE '2027-03-31');

INSERT INTO presupuestos (proyecto_id, version, tipo, estado, es_base_control, moneda,
                          fecha_base, clase_estimado, creado_por)
SELECT id, 1, 'oferente', 'aprobado', true, 'USD', DATE '2026-08-01', 'Clase 3', 'ORQ-COST'
  FROM proyectos WHERE codigo = 'SOT-2026-014';

INSERT INTO partidas (presupuesto_id, proyecto_id, codigo_covenin, codigo_interno, capitulo,
                      descripcion, unidad, cantidad, precio_unitario, especialidad,
                      etiqueta_cantidad, fuente_cantidad, etiqueta_precio, fuente_precio,
                      agente_responsable, orden)
SELECT pr.id, pr.proyecto_id, v.covenin, v.codigo, v.capitulo, v.descripcion, v.unidad,
       v.cantidad, v.precio, v.especialidad, 'confirmado', v.fuente,
       'referencial', 'CIV-DataLaing ago-2026 (demo)', 'SUB-CM', v.orden
  FROM presupuestos pr
  JOIN proyectos p ON p.id = pr.proyecto_id AND p.codigo = 'SOT-2026-014'
  CROSS JOIN (VALUES
    ('E.2.1', 'FUN-001', 'Fundaciones', 'Excavación a máquina en tierra común, prof. hasta 2,00 m',
     'm3', 480.0, 12.50, 'civil', 'Plano E-01, planta de fundaciones', 1),
    ('E.2.4', 'FUN-002', 'Fundaciones', 'Concreto f''c=250 kgf/cm2 en zapatas, premezclado',
     'm3', 96.0, 210.00, 'civil', 'Plano E-02, cuadro de zapatas', 2),
    ('E.2.6', 'FUN-003', 'Fundaciones', 'Acero de refuerzo fy=4200 kgf/cm2 en fundaciones',
     'kg', 9800.0, 2.15, 'civil', 'Plano E-02, despiece', 3),
    ('E.3.1', 'EST-001', 'Estructura', 'Concreto f''c=250 kgf/cm2 en columnas',
     'm3', 72.0, 245.00, 'civil', 'Plano E-03', 4),
    ('E.4.2', 'ALB-001', 'Albañilería', 'Pared de bloque de arcilla 15 cm',
     'm2', 1240.0, 28.00, 'civil', 'Planos A-02 a A-05', 5)
  ) AS v(covenin, codigo, capitulo, descripcion, unidad, cantidad, precio, especialidad, fuente, orden);

INSERT INTO planificacion_partida (partida_id, proyecto_id, fecha_inicio, fecha_fin,
                                   cantidad_plan, rendimiento_declarado, origen)
SELECT pa.id, pa.proyecto_id, v.inicio, v.fin, pa.cantidad, v.rend, 'SUB-DOC'
  FROM partidas pa
  JOIN proyectos p ON p.id = pa.proyecto_id AND p.codigo = 'SOT-2026-014'
  JOIN (VALUES
    ('FUN-001', DATE '2026-09-01', DATE '2026-09-25', '60 m3/día, 1 retroexcavadora'),
    ('FUN-002', DATE '2026-09-15', DATE '2026-10-20', '8 m3/día, 1 cuadrilla'),
    ('FUN-003', DATE '2026-09-10', DATE '2026-10-20', '350 kg/día, 2 cabilleros'),
    ('EST-001', DATE '2026-10-15', DATE '2026-12-10', '4 m3/día'),
    ('ALB-001', DATE '2026-11-01', DATE '2027-02-15', '35 m2/día, 3 cuadrillas')
  ) AS v(codigo, inicio, fin, rend) ON v.codigo = pa.codigo_interno;

INSERT INTO mediciones (partida_id, referencia, expresion, subtotal, unidad, etiqueta, agente)
SELECT pa.id, 'Plano E-02, cuadro de zapatas Z-1 (12 und)', '12*(2.00*2.00*0.50)', 24.0,
       'm3', 'confirmado', 'SUB-CM'
  FROM partidas pa JOIN proyectos p ON p.id = pa.proyecto_id
 WHERE p.codigo = 'SOT-2026-014' AND pa.codigo_interno = 'FUN-002';

INSERT INTO faltantes (proyecto_id, ambito, descripcion, impacto_estimado, como_obtenerlo, agente)
SELECT id, 'Fundaciones',
       'No hay estudio de suelos cargado. Las cantidades de excavación asumen tierra común '
       'sin presencia de roca ni nivel freático.',
       'Alto: un cambio de tipo de excavación o de fundación reconstruye el capítulo completo.',
       'Solicitar el estudio geotécnico al cliente o cotizar ensayos SPT + CBR.',
       'SUB-CM'
  FROM proyectos WHERE codigo = 'SOT-2026-014';
