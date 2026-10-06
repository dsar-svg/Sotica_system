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

El `.env` debe tener `OPENAI_API_KEY`, `SOTICA_MODEL=gpt-5` y la base en el puerto 5433.
**No usar `gpt-4o` para la demo**: en las pruebas inventó longitudes y diámetros de tubería.

## Recorrido

Las cuatro órdenes están como sugerencias en la pantalla inicial del chat.

### 1. Estado de la obra sin datos — "no inventa"

Mostrar la pestaña **Avance** antes de escribir nada: 0 % real contra 30,81 % planificado y el aviso
en rojo *"No hay avances cargados… No asumir que la obra sigue el cronograma"*.

Qué decir: el sistema distingue "no ha avanzado" de "no tengo información".

### 2. Cómputo y libro de Excel

> Computa las paredes de bloque de la planta baja: 45 m lineales por 2,80 m de altura, descontando
> 6 puertas de 0,90 x 2,10. Regístralo y genera el libro de cómputos en Excel.

- En el chat aparecen los pasos **SUB-CM · cómputos** y **SUB-DOC · documentos**.
- Resultado: 114,66 m². En **Presupuesto** aparece la partida en el borrador v2, etiquetada.
- En **Archivos**, abrir `SOTICA-CM-01`: la hoja de medición trae el despiece como fórmula viva.
- En **Quién hizo qué** queda cada delegación con las herramientas que el especialista usó.

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

En **Avance → Cargar reporte de campo**, pegar:

> Semana del 28/09 al 03/10: se terminó la excavación de fundaciones, los 480 m3 completos según
> levantamiento topográfico. Se vaciaron 14 zapatas de 2,00 x 2,00 x 0,50 m. También se construyó
> una tanquilla de aguas blancas de 1,5 x 1,5 m que pidió el inspector.

Luego en el chat:

> Procesa el reporte de avance pendiente del residente.

- Avance físico pasa a 11,93 % contra 30,81 % planificado: obra atrasada, y lo dice.
- La tanquilla no está en el presupuesto: aparece **1** en la pestaña **Bloqueos** y no suma.
- Cerrar el bloqueo en el chat: *"La tanquilla es obra extra, difiérela a obra extra."*

Qué decir: el presupuesto base no se toca desde obra; lo que no encaja espera una decisión humana.

## Lo que hoy NO hace (decirlo si preguntan)

- Solo están activos ORQ-COST, SUB-CM, SUB-DOC y SUB-AVA. Eléctrico, hidráulico, estructural,
  vialidad y suelos están escritos pero apagados.
- Genera Excel (cómputos y presupuesto). Word, PowerPoint y Gantt no están construidos.
- No lee planos en PDF ni interpreta el contenido de las fotos: trabaja con lo que se le escribe.
- El presupuesto es **costo directo**: indirectos, utilidad, impuestos y FCAS esperan datos de SOTICA.
- Los precios de internet son aproximados, y los consumos de material por unidad que no dé el
  usuario los infiere el modelo y los declara como supuesto.
- No hay usuarios ni contraseñas, ni pantalla para crear una obra nueva.

## Si algo falla en vivo

- **"No se pudo completar"** en el chat: reintentar el mismo mensaje.
- **El panel no carga**: revisar que `demo_start.ps1` siga corriendo.
- **ORQ-COST arrastra contexto de una prueba anterior**: botón **Conversación nueva**.
