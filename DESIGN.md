---
name: SOTICA-COSTOS
description: Oficina de presupuestos asistida por agentes, señalizada como una vía venezolana.
colors:
  rojo-reglamentario: "#CB0C0C"
  rojo-fuerte: "#A30909"
  rojo-suave: "#FCEBEB"
  azul-placa: "#002E54"
  azul-tinta: "#0B4677"
  azul-suave: "#E7EEF5"
  amarillo-preventivo: "#F2B705"
  amarillo-suave: "#FFF6D6"
  verde: "#0B6E3A"
  verde-suave: "#E4F3EA"
  fondo: "#FFFFFF"
  sup-2: "#F3F5F7"
  sup-3: "#E9EDF1"
  borde: "#E1E5EA"
  borde-fuerte: "#C5CDD5"
  tinta: "#12171C"
  tinta-2: "#434D57"
  tinta-3: "#5F6B76"
  asfalto: "#15191E"
  asfalto-sup: "#1B2026"
  sb-oscuro: "#8F0A0A"
typography:
  display:
    fontFamily: "Barlow Semi Condensed, Bahnschrift SemiCondensed, Bahnschrift, Arial Narrow, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.005em"
  headline:
    fontFamily: "Barlow Semi Condensed, Bahnschrift SemiCondensed, Bahnschrift, Arial Narrow, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1
  title:
    fontFamily: "Barlow Semi Condensed, Bahnschrift SemiCondensed, Bahnschrift, Arial Narrow, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.01em"
  body:
    fontFamily: "Barlow, Bahnschrift, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "tnum"
  label:
    fontFamily: "Barlow Semi Condensed, Bahnschrift SemiCondensed, Bahnschrift, Arial Narrow, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.02em"
    fontFeature: "tnum"
  label-caps:
    fontFamily: "Barlow Semi Condensed, Bahnschrift SemiCondensed, Bahnschrift, Arial Narrow, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.08em"
rounded:
  tramo: "4px"
  etiqueta: "5px"
  placa: "6px"
  control: "8px"
  bloque: "10px"
  menu: "12px"
  dialogo: "16px"
  burbuja: "18px"
  compositor: "22px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.rojo-reglamentario}"
    textColor: "{colors.fondo}"
    typography: "{typography.title}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.rojo-fuerte}"
  button-secondary:
    backgroundColor: "{colors.fondo}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "38px"
  button-secondary-hover:
    backgroundColor: "{colors.sup-2}"
  button-send:
    backgroundColor: "{colors.rojo-reglamentario}"
    textColor: "{colors.fondo}"
    size: "36px"
  input-field:
    backgroundColor: "{colors.fondo}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  composer:
    backgroundColor: "{colors.fondo}"
    rounded: "{rounded.compositor}"
    padding: "12px 12px 10px 16px"
  route-panel:
    backgroundColor: "{colors.azul-placa}"
    textColor: "{colors.fondo}"
    rounded: "{rounded.placa}"
    padding: "8px 12px"
  route-plate:
    backgroundColor: "{colors.azul-placa}"
    textColor: "{colors.fondo}"
    typography: "{typography.label}"
    rounded: "{rounded.etiqueta}"
    padding: "5px 10px"
  tag-confirmado:
    backgroundColor: "{colors.fondo}"
    textColor: "{colors.tinta}"
    typography: "{typography.label}"
    rounded: "{rounded.etiqueta}"
    height: "22px"
  tag-inferido:
    backgroundColor: "{colors.azul-placa}"
    textColor: "{colors.fondo}"
    typography: "{typography.label}"
    rounded: "{rounded.etiqueta}"
    height: "22px"
  tag-referencial:
    backgroundColor: "{colors.sup-3}"
    textColor: "{colors.tinta-2}"
    typography: "{typography.label}"
    rounded: "{rounded.etiqueta}"
    height: "22px"
  tag-pendiente:
    backgroundColor: "{colors.amarillo-preventivo}"
    textColor: "{colors.tinta}"
    typography: "{typography.label}"
    rounded: "{rounded.etiqueta}"
    height: "22px"
  card-bloque:
    backgroundColor: "{colors.fondo}"
    rounded: "{rounded.bloque}"
    padding: "16px"
  sidebar:
    backgroundColor: "{colors.rojo-reglamentario}"
    textColor: "{colors.fondo}"
    width: "264px"
    padding: "16px 12px 12px"
---

# Design System: SOTICA-COSTOS

## Overview

**Creative North Star: "Señalética vial"**

El panel se lee como una vía venezolana bien señalizada: rojo reglamentario para lo que detiene o manda, azul informativo para lo que orienta, amarillo preventivo para lo que está pendiente. El rojo SOTICA (tomado de sotica.com.ve) ocupa el sidebar a toda altura como una placa reglamentaria; el área de trabajo es blanca y sobria, y el azul aparece solo donde algo indica camino o procedencia. El sistema rechaza el chat genérico gris con un acento suelto.

La materia son placas: superficies de esquina redondeada con un filete interior blanco, como las señales de tránsito, rotuladas en Barlow Semi Condensed (una DIN libre) con cifras tabulares en toda cantidad. La densidad es de herramienta de ingeniería: tablas compactas, medida de lectura fija, nada decorativo que no informe. Claro por defecto (oficina de día, proyector); el tema oscuro es asfalto, con el rojo del sidebar oscurecido para no encandilar.

**Key Characteristics:**
- Sidebar rojo reglamentario a toda altura con texto blanco; trabajo sobre blanco (oscuro: asfalto).
- Placas con filete interior blanco para marca, autor, ruta y etiquetas de certeza.
- Panel direccional azul de delegación (ORQ-COST → SUB-CM → SUB-DOC) como gesto distintivo.
- Rotulación DIN (Barlow / Barlow Semi Condensed) y cifras tabulares en todo el cuerpo.
- La certeza de cada dato se dice siempre con texto, nunca solo con color.

## Colors

Tres colores de señal con roles fijos sobre un neutro frío de oficina; cada color significa una cosa.

### Primary
- **Rojo Reglamentario SOTICA** (rojo-reglamentario): sidebar, botón de enviar, botón primario, pestaña activa del registro, cabecera de diálogo, placa de autor de ORQ-COST, hito de plan en la pista de avance, etiqueta de alerta. En oscuro sube a #E5322F para contraste sobre asfalto.
- **Rojo Fuerte** (rojo-fuerte): hover del rojo y tinta roja sobre placas blancas dentro del sidebar (botón "Nueva conversación", ítem de navegación y conversación activos, contador de bloqueos).
- **Rojo Suave** (rojo-suave): fondo de avisos de error y de bloqueo.

### Secondary
- **Azul Placa Informativa** (azul-placa): panel direccional de delegación, placas de ruta en las órdenes sugeridas, etiqueta "inferido", barra de la pista de avance. En oscuro pasa a #0E4A80.
- **Azul Tinta** (azul-tinta): enlaces, anillo de foco, borde de campo enfocado, botón de barra presionado.
- **Azul Suave** (azul-suave): halo de foco de campos y compositor, fondo de aviso informativo y del botón de barra presionado.

### Tertiary
- **Amarillo Preventivo** (amarillo-preventivo): etiqueta "pendiente", punto de "trabajando", punto de entregable nuevo. Sobre amarillo, el texto es siempre casi negro.
- **Amarillo Suave** (amarillo-suave): fondo del aviso preventivo.
- **Verde** (verde) y **Verde Suave** (verde-suave): solo la etiqueta "ok"; no es color de marca.

### Neutral
- **Blanco de oficina** (fondo): fondo de trabajo y superficie de bloques, campos y compositor.
- **Gris lámina** (sup-2): fondo del registro, hover de filas y menús, chips de herramienta.
- **Gris lámina profunda** (sup-3): burbuja del usuario, pista vacía, etiqueta "referencial", estado deshabilitado.
- **Borde** (borde) y **Borde fuerte** (borde-fuerte): divisores de 1px; el fuerte para campos, compositor y botón secundario.
- **Tinta** (tinta), **Tinta 2** (tinta-2), **Tinta 3** (tinta-3): texto principal, secundario y metadatos/placeholder.
- **Asfalto** (asfalto) y **Asfalto superficie** (asfalto-sup): fondo y superficie del tema oscuro.
- **Rojo nocturno** (sb-oscuro): sidebar en tema oscuro.

### Named Rules
**The Una Señal, Un Significado Rule.** Rojo detiene o manda, azul orienta o atribuye, amarillo advierte de algo pendiente. No se usa azul para un error ni amarillo como decoración.

**The Rojo Es el Sidebar Rule.** En el área de trabajo el rojo es escaso: enviar, el botón primario de un formulario, la pestaña activa, el hito y las alertas. Nunca fondos rojos amplios fuera del sidebar y la cabecera de diálogo.

## Typography

**Display Font:** Barlow Semi Condensed (con Bahnschrift SemiCondensed, Bahnschrift, Arial Narrow)
**Body Font:** Barlow (con Bahnschrift, Segoe UI, system-ui)

**Character:** Rotulación tipo DIN de carretera: el semicondensado nombra (títulos, etiquetas, códigos, cifras destacadas) y Barlow lee. Las dos se sirven desde el proyecto (`frontend/fonts/`, woff2 latino, licencia OFL), así que se ven igual sin conexión; Bahnschrift, la DIN de Windows, queda como último respaldo.

### Hierarchy
- **Display** (600, 30px, 1.15; 25px en móvil): solo el título del estado vacío del chat.
- **Headline** (600, 20px, 1): cabecera de diálogo; cifras destacadas del registro (20px) y porcentaje de avance (28px).
- **Title** (600, 15-17px, 1.2-1.3): título de la barra, cabecera del registro, títulos de bloque (16px), de orden sugerida (16px), de ítem (15px), h3 de prosa (17px).
- **Body** (400, 15px, 1.55): prosa del chat a 68ch máximo; tablas y avisos a 13.5-14px.
- **Label** (600, 12.5-13.5px, 0.02em): etiquetas de certeza, placas de ruta, encabezados de tabla, rótulos de campo, códigos de partida.
- **Label caps** (600, 12px, 0.08em, mayúsculas): solo rótulos de grupo dentro del sidebar ("Obra", "Registro de la obra").

### Named Rules
**The Cifra Tabular Rule.** Toda cantidad se compone con cifras tabulares (`tabular-nums` en el body) y alineada a la derecha en tablas; las cifras nunca bailan entre filas.

**The Rótulo Nombra, Texto Lee Rule.** Lo que identifica (código, título, etiqueta, encabezado) va en Barlow Semi Condensed; lo que se lee de corrido va en Barlow.

## Layout

Armazón de tres columnas en rejilla: sidebar rojo de 264px, columna de chat flexible con contenido centrado a 760px, y registro plegable de 460px a la derecha (columna 0 cuando está cerrado; transición de 0.28s). La barra superior y la cabecera del registro miden 58px. La prosa del chat se sangra 38px bajo la placa de autor y se limita a 68ch.

Ritmo sobre retícula de 8px con medios pasos: 4, 8, 12, 16, 24 y 28px (separación entre turnos 28px; padding de bloques 16px; columna del chat 28px 24px arriba y a los lados).

Responsivo: por debajo de 1240px el registro pasa a hoja superpuesta desde la derecha con velo; por debajo de 880px el sidebar sale del lienzo (min(300px, 86vw)) con botón de menú, las órdenes sugeridas apilan su placa de ruta debajo, desaparece la sangría de 38px y el título vacío baja a 25px.

## Elevation & Depth

Plano por defecto: la profundidad se da por tono (blanco sobre gris lámina en el registro) y bordes de 1px. Solo dos sombras: una ambiental baja para el compositor, y una elevada para lo que flota sobre el trabajo (menú de adjuntar, diálogo, registro y sidebar superpuestos). Los filetes de las placas se hacen con sombras interiores, que no elevan.

### Shadow Vocabulary
- **sombra-1** (`box-shadow: 0 1px 2px rgba(18,23,28,.06), 0 2px 8px rgba(18,23,28,.06)`): compositor en reposo.
- **sombra-2** (`box-shadow: 0 8px 28px rgba(18,23,28,.14), 0 2px 6px rgba(18,23,28,.08)`): menús, diálogo, hojas superpuestas.
- **Filete de placa** (`box-shadow: inset 0 0 0 2px <color de placa>, inset 0 0 0 3.5px rgba(255,255,255,.92)`): el borde blanco interior de la señal.

### Named Rules
**The Lo Que Flota Se Eleva Rule.** Solo lleva sombra-2 lo que se superpone al trabajo; bloques y tarjetas del registro son planos con borde.

## Shapes

Esquinas redondeadas de señal, nunca vivas ni píldora salvo en el compositor y los controles circulares. Escala: tramo 4px, etiqueta 5px, placa 6px, control 8px, bloque y aviso 10px, menú 12px, diálogo 16px, burbuja de usuario 18px (esquina inferior derecha 4px), compositor 22px; enviar es un círculo. El filete interior blanco (1.5-3.5px por sombra interior) es la firma de forma: marca, placa de autor, placa de ruta, panel de delegación, "Nueva conversación", contador de bloqueos y etiquetas de inferido y alerta.

## Components

### Buttons
- **Shape:** control de 8px (botones de formulario y barra); enviar circular de 36px.
- **Primary:** rojo reglamentario, texto blanco en rótulo 600 15px, 38px de alto, 0 16px.
- **Hover / Focus:** hover a rojo fuerte; foco con anillo de 2px en azul tinta y 2px de separación (blanco dentro del sidebar). Enviar se comprime a 0.94 al pulsar.
- **Secondary:** superficie blanca con borde fuerte y tinta; hover gris lámina.
- **Barra:** 36px, borde de 1px, tinta 2; presionado pasa a azul suave con tinta azul.
- **Disabled:** gris lámina profunda con tinta 3.

### Chips
- **Etiquetas de certeza** (22px, radio 5px, rótulo 600 12.5px), siempre con su palabra: confirmado (blanco con borde de tinta), inferido (placa azul con filete blanco), referencial (gris con borde fuerte), pendiente (amarillo con borde casi negro), alerta (rojo con filete blanco), ok (verde suave).
- **Herramienta:** chip gris lámina, Barlow 500 12.5px, tinta 3; informa qué herramienta usó el agente.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** blanco sobre el gris lámina del registro.
- **Shadow Strategy:** ninguna (ver Elevation & Depth).
- **Border:** 1px borde.
- **Internal Padding:** 16px; separación entre bloques 12px.
- **Avisos:** misma forma sin borde, fondo suave de su señal (amarillo, rojo, azul) e icono SVG del color de la señal.

### Inputs / Fields
- **Style:** borde fuerte de 1px, radio 8px, fondo blanco, 8px 10px; rótulo en Barlow Semi Condensed 600 13px.
- **Focus:** borde azul tinta con halo de 3px azul suave. El compositor (radio 22px, sombra-1) usa el mismo foco con su sombra.

### Navigation
- **Sidebar:** botones de 8px de radio, Barlow 500 15px, iconos SVG de trazo 1.75; hover oscurece 14%. El activo es una placa blanca con tinta roja fuerte. Contadores de bloqueo como mini placa blanca con filete rojo; valores en rótulo a la derecha.
- **Pestañas del registro:** rótulo 600 14px en tinta 3; la activa en tinta con subrayado rojo de 3px.
- **Móvil:** sidebar fuera del lienzo con velo; el registro, hoja superpuesta.

### Panel direccional de delegación (signature)
Placa azul con filete blanco interior y radio 6px que muestra la ruta ORQ-COST → SUB-CM → SUB-DOC en rótulo 600 13.5px. Los tramos por venir van en blanco al 62%, los hechos en blanco con check, y el tramo activo se ilumina: placa blanca con tinta azul y un punto rojo de 7px. El mismo lenguaje, como placa de ruta compacta (radio 5px), acompaña cada orden sugerida del estado vacío indicando a qué especialista va.

## Do's and Don'ts

### Do:
- **Do** dar a cada dato su etiqueta de certeza con texto (confirmado, inferido, referencial, pendiente); el color refuerza, nunca reemplaza.
- **Do** usar el azul de placa para todo lo que indique ruta, delegación o procedencia, y el amarillo solo para lo pendiente.
- **Do** componer toda cantidad con cifras tabulares y alinearla a la derecha en tablas.
- **Do** construir las placas con el filete interior blanco por sombra interior, no con bordes externos.
- **Do** mantener la prosa del chat a 68ch y el contenido del chat centrado a 760px.
- **Do** probar cada componente en claro y en oscuro (asfalto); el tema oscuro redefine tokens, no componentes.

### Don't:
- **Don't** convertir el panel en un chat genérico gris con un acento suelto: el rojo vive en el sidebar y las señales tienen roles.
- **Don't** comunicar un estado solo con color, ni un punto sin texto accesible.
- **Don't** usar el rojo como fondo amplio fuera del sidebar y la cabecera de diálogo.
- **Don't** dar sombra elevada a bloques del registro; solo flota lo que se superpone.
- **Don't** usar caracteres o emojis como iconos: los iconos son SVG de trazo.

## Gráficas y pantalla de avance (extensión, 06/10/2026)

- **Series de datos**, validadas con el validador de paleta (luminosidad, croma, daltonismo y contraste): real `#2563A8` y plan `#B0702A` en claro; real `#4A8BD6` y plan `#C28040` en oscuro (`--serie-real`, `--serie-plan`). El plan es ocre, nunca el amarillo de estado, y es el mismo en la curva S, en las barras de partidas y en la marca del panel de capítulos.
- **Curva S**: un solo eje en %, líneas de 2–2,5 px, rejilla de 1 px sólida, línea «Hoy», rótulos directos al final de cada serie, cruz con tooltip al pasar el cursor o con las flechas, y vista en tabla. El real termina en el último avance registrado: nunca se proyecta.
- **Panel de ruta por capítulos**: placa azul con filete blanco, un tramo por capítulo con real contra plan; el tramo seleccionado es placa blanca con tintas fijas (`#002E54`, atraso `#A30909`) en ambos temas.
- **Indicadores**: franja de celdas con rótulo semicondensado, cifra grande y línea secundaria; la certeza del dato va como placa debajo.
