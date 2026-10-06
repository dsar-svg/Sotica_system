# Guion de la demostración — SOTICA-COSTOS

Recorrido probado de punta a punta con `gpt-5` contra la base real. Dura unos 15–20 minutos;
cada orden tarda entre 1 y 4 minutos en responder (el panel muestra el tiempo y qué agente trabaja).

## Antes de empezar

1. Dejar la base en el estado inicial (borra lo de pruebas anteriores):

   ```powershell
   .\scripts\db_start.ps1
   .\.venv\Scripts\python.exe -m scripts.reset_demo
   ```

2. Arrancar el panel y abrir <http://localhost:8000>:

   ```powershell
   .\scripts\demo_start.ps1
   ```

3. Tener Excel a mano para abrir los archivos que se generan.
4. Con la VPN activa (OpenAI no atiende desde Venezuela), correr el chequeo previo:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.verificar_demo
   ```

El `.env` debe tener `OPENAI_API_KEY`, `SOTICA_MODEL=gpt-5` y la base en el puerto 5433.
**No usar `gpt-4o` para la demo**: en las pruebas inventó longitudes y diámetros de tubería.

## Recorrido

Las órdenes están como sugerencias en la pantalla inicial del chat (cambian según sea oferta u obra).

### 0. El ciclo comercial — ofertas y obras

El sidebar separa **Ofertas en estudio** (sin contrato: cómputo, APU, presupuesto, propuesta) de **Obras en
ejecución** (con control de avance). La demo trae una de cada una: la oferta `SOT-2026-021` (galpón) y la obra
`SOT-2026-014`. Con **Nuevo proyecto** se abre una oferta escribiendo solo el nombre; el código se asigna solo.
Al ganarla, **Fase → Marcar como adjudicada** fija el plazo y convierte el presupuesto ofertado en base de control.

Qué decir: no hace falta "crear una obra" para cotizar algo que todavía no es seguro.

### 1. Estado de la obra sin datos — "no inventa"

En la obra `SOT-2026-014`, abrir **Avance de obra** en el sidebar antes de escribir nada: 0 % real contra el
planificado a la fecha (~31 %), el panel de capítulos y el aviso en rojo *"No hay avances cargados… No asumir que
la obra sigue el cronograma"*.

Qué decir: el sistema distingue "no ha avanzado" de "no tengo información".

### 2. Cómputo y libro de Excel

> Computa las paredes de bloque de la planta baja: 45 m lineales por 2,80 m de altura, descontando
> 6 puertas de 0,90 x 2,10. Regístralo y genera el libro de cómputos en Excel.

- En el chat aparecen los pasos **SUB-CM · cómputos** y **SUB-DOC · documentos**.
- Resultado: 114,66 m². En **Presupuesto** aparece la partida en el borrador v2, etiquetada.
- En **Archivos**, abrir `SOTICA-CM-01`: la hoja de medición trae el despiece como fórmula viva.
- En **Quién hizo qué** queda cada delegación con las herramientas que el especialista usó.

### 2b. Cómputo desde un plano en PDF

En **Archivos → Planos de la obra**, subir `docs/demo/plano_A-02_planta_alta.pdf` (si falta, generarlo
con `python -m scripts.plano_demo`). Luego en el chat (también está como sugerencia):

> Computa las paredes de bloque de la planta alta a partir del plano A-02 que subí en Archivos.
> Regístralo en el borrador.

- SUB-CM llama `listar_planos` y `leer_plano_pdf`: aparece en **Quién hizo qué**.
- Resultado esperado: 60,00 m de muro × 2,80 m = 168,00 m², menos 4 puertas P-1 (7,56 m²) y
  6 ventanas V-1 (10,80 m²) = **149,64 m²**. La referencia de la hoja de medición cita la lámina A-02.

Qué decir: lee el texto del plano (rótulo, cotas, cuadros); si el PDF es un escaneo sin texto lo dice
y pide las cotas, no las inventa.

### 3. Precios con respaldo

> Ponle precio a la partida de paredes. No tengo cotizaciones: busca precios aproximados de los
> materiales en internet. Mano de obra por experiencia del Ing. Pérez: 1 albañil a 40 USD/día y
> 1 ayudante a 25 USD/día, rendimiento 12 m2 por día. Luego genera el presupuesto en Excel.

- A veces ORQ-COST pregunta antes (tipo de bloque, dosificación del mortero, desperdicios). Responder
  y sigue. Es el comportamiento pedido: máximo 5 preguntas, priorizadas.
- Busca en internet, registra cada material con **enlace y fecha** y lo marca *Referencial*.
- Abrir `SOTICA-PRE-01`, hoja **APU**: cada insumo con origen, proveedor, enlace, fecha y quién lo cargó.

Variante para mostrar la regla dura: dar un precio de proveedor **sin enlace**. La partida queda
*Pendiente de confirmar* y su monto sale del total firme, en columna aparte.

Qué decir: la etiqueta la pone el sistema según la evidencia, no la IA; y la base de datos rechaza
una cotización "firme" sin proveedor, enlace y fecha.

### 4. Avance de obra

En **Avance de obra → Cargar reporte**, pegar:

> Semana del 28/09 al 03/10: se terminó la excavación de fundaciones, los 480 m3 completos según
> levantamiento topográfico. Se vaciaron 14 zapatas de 2,00 x 2,00 x 0,50 m. También se construyó
> una tanquilla de aguas blancas de 1,5 x 1,5 m que pidió el inspector.

Luego en el chat:

> Procesa el reporte de avance pendiente del residente.

- Avance físico pasa a 11,93 % contra el planificado a la fecha: obra atrasada, y lo dice.
- En **Avance de obra**: la curva S real arranca y se queda en el último reporte (no se proyecta), el tramo
  **Fundaciones** del panel de capítulos se marca atrasado y la bitácora muestra el reporte procesado.
- La tanquilla no está en el presupuesto: aparece **1** en **Bloqueos** y no suma.
- Cerrar el bloqueo en el chat: *"La tanquilla es obra extra, difiérela a obra extra."*

Qué decir: el presupuesto base no se toca desde obra; lo que no encaja espera una decisión humana.

### 5. Orden mixta — "un equipo, no un prompt" (§11.1)

> Vamos a ofertar un anexo de servicios de una planta, 12 x 8 m: estructura de concreto armado
> (6 columnas de 0,30 x 0,30 m y 3,00 m de alto sobre zapatas aisladas, losa nervada de 25 cm; no hay
> estudio de suelos), red de aguas servidas hasta
> la cloaca existente (2 baños, el plano de cloacas no tiene diámetros), instalación eléctrica con un
> tablero nuevo y 16 luminarias, y el cronograma de la obra. Dame el paquete integrado.

- En el chat aparecen al menos cuatro especialistas: **SUB-EST**, **SUB-HID** y **SUB-ELE**, más SUB-CM,
  SUB-DOC o SUB-SUE según el caso (en el ensayo: cinco). Tarda unos 3 minutos.
- **Bandera roja de suelos**: las fundaciones quedan no computables sin estudio de suelos (§4.7).
- El cronograma del anexo suele quedar pendiente hasta tener retícula, diámetros y unifilar: es correcto,
  no inventa duraciones. El Gantt de la obra se muestra en el paso 7.
- SUB-HID **no inventa diámetros**: la red queda PENDIENTE DE CONFIRMACIÓN con su impacto.
- En **Quién hizo qué** queda el dictamen de cada uno.

Qué decir: ORQ-COST reparte, cada especialista responde en su dominio y ORQ-COST integra; el juicio de
un especialista no se silencia, se anexa.

### 6. Precio de oferta

> Para el presupuesto usa administración y gastos generales 15 %, utilidad 10 % e IVA 16 %; es decisión
> de SOTICA. Genera el presupuesto en Excel.

- ORQ-COST registra los porcentajes con la cita del usuario; SUB-DOC rehace SOTICA-PRE-01.
- Hoja **Indirectos**: costo directo → administración → utilidad → IVA → **precio de oferta**, todo con
  fórmulas vivas y la fuente de cada porcentaje.

Qué decir: el sistema no supone porcentajes "típicos"; sin ellos, el precio de oferta queda pendiente.

### 7. Cronograma, curva S e informe

> Genera el cronograma Gantt de la obra y dime si es coherente con los rendimientos. Después prepara el
> informe de avance en Word y una presentación corta para la junta.

- `SOTICA-PLA-01`: hojas Gantt (columna Coherencia contra rendimientos), Curva S, Premisas, Hitos.
- `SOTICA-INF-01` (Word): portada, control de revisiones y las 8 secciones del formato; lo que no hay
  queda PENDIENTE DE CONFIRMACIÓN.
- `SOTICA-PRS-01` (PowerPoint).

### 8. FIDIC + pliego (§11.8)

> El contrato es FIDIC Libro Rojo adaptado. FIDIC da 56 días para pagar cada certificado, pero el pliego
> del ente dice 30 días. ¿Cuál manda y qué hago en la oferta?

- Responde que manda el pliego venezolano y declara la desviación.

### Opcional: clientes

**Clientes** en el sidebar: RIF, contacto, ubicación, norma y moneda habituales. Al crear un proyecto se elige
el cliente y esos datos se rellenan solos. Un cliente con proyectos no se puede borrar.

## Lo que hoy NO hace (decirlo si preguntan)

- Lee el texto de planos PDF exportados desde CAD, no el dibujo ni escaneos (no hay OCR). No
  interpreta el contenido de las fotos.
- Los PDF de los entregables no se generan solos: se exportan desde Excel, Word o PowerPoint.
- FCAS, administración, utilidad e impuestos solo se aplican si SOTICA o el pliego los dan.
- Los precios de internet son aproximados, y los consumos de material por unidad que no dé el
  usuario los infiere el modelo y los declara como supuesto.
- Los especialistas emiten dictamen y cómputo de presupuesto, no proyecto firmado (§12).
- No hay usuarios ni contraseñas.

## Si algo falla en vivo

- **"OpenAI rechazó la conexión por la región"**: se cayó la VPN. Reactivarla y reintentar el mensaje.

- **"No se pudo completar"** en el chat: reintentar el mismo mensaje.
- **El panel no carga**: revisar que `demo_start.ps1` siga corriendo.
- **ORQ-COST arrastra contexto de una prueba anterior**: botón **Conversación nueva**.
