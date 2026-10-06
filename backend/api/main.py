"""API HTTP del ciclo 1: chat con ORQ-COST, carga de evidencia y panel de archivos."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..core import avance as avance_mod
from ..core import apu, control, db, storage
from ..core.config import BASE_DIR, STORAGE_DIR
from ..core import orchestrator

app = FastAPI(title="SOTICA-COSTOS", version="ciclo-1")

# ORQ-COST con sus servidores MCP: uno por proceso, compartido por todas las conversaciones.
_motor: orchestrator.Motor | None = None
_motor_lock = asyncio.Lock()


async def _motor_listo() -> orchestrator.Motor:
    global _motor
    async with _motor_lock:
        if _motor is None:
            motor = orchestrator.Motor()
            await motor.abrir()
            _motor = motor
    return _motor


@app.on_event("shutdown")
async def _cerrar() -> None:
    if _motor is not None:
        await _motor.cerrar()
    await db.close_pool()


async def _proyecto(ref: str):
    async with db.acquire() as conn:
        p = await control.proyecto_por_ref(conn, ref)
    if p is None:
        raise HTTPException(404, f"No existe la obra '{ref}'.")
    return p


# ---------------------------------------------------------------------------
# Obras
# ---------------------------------------------------------------------------

@app.get("/api/proyectos")
async def listar_proyectos() -> list[dict[str, Any]]:
    filas = await db.fetch(
        """
        SELECT p.id, p.codigo, p.nombre_obra, p.cliente, p.cliente_id, p.tipo_obra, p.moneda_base,
               p.fase, p.fecha_inicio_contractual, p.fecha_fin_contractual, p.creado_en,
               eo.pct_fisico_real, eo.pct_fisico_plan, eo.ultima_fecha_avance,
               eo.dias_sin_reporte, eo.bloqueos_abiertos, eo.desviaciones_abiertas,
               pr.version AS presupuesto_version, pr.partidas, pr.costo_directo,
               pr.adm_pct, pr.utilidad_pct, pr.impuesto_pct,
               (SELECT max(c.actualizado_en) FROM conversaciones c
                 WHERE c.proyecto_id = p.id) AS ultima_conversacion_en,
               (SELECT c.id FROM conversaciones c WHERE c.proyecto_id = p.id
                 ORDER BY c.actualizado_en DESC LIMIT 1) AS ultima_conversacion
          FROM proyectos p
          LEFT JOIN estado_obra eo ON eo.proyecto_id = p.id
          -- El presupuesto que se ve en la lista: el último (borrador de oferta o base de control).
          LEFT JOIN LATERAL (
                SELECT x.version, x.adm_pct, x.utilidad_pct, x.impuesto_pct,
                       count(pa.id) AS partidas, sum(pa.monto) AS costo_directo
                  FROM presupuestos x LEFT JOIN partidas pa ON pa.presupuesto_id = x.id
                 WHERE x.proyecto_id = p.id
                 GROUP BY x.id ORDER BY x.version DESC LIMIT 1) pr ON true
         WHERE p.estado = 'activo'
         ORDER BY p.fase, p.creado_en DESC
        """
    )
    salida = []
    for f in filas:
        d = dict(f)
        d["precio_oferta"] = (apu.precio_oferta(float(d["costo_directo"]), d["adm_pct"],
                                                d["utilidad_pct"], d["impuesto_pct"])
                              if d["costo_directo"] is not None else None)
        salida.append(d)
    return salida


_TIPOS_OBRA = {"edificacion", "vialidad", "hidraulica", "electrificacion", "industrial"}
_TIPOS_ENTE = {"publico_nacional", "publico_estadal", "publico_municipal", "privado",
               "multilateral"}


def _textos(datos: dict[str, Any]):
    def texto(campo: str) -> str | None:
        valor = str(datos.get(campo) or "").strip()
        return valor or None
    return texto


_CAMPOS_CLIENTE = ("nombre", "rif", "tipo_ente", "contacto_nombre", "contacto_cargo", "telefono",
                   "correo", "direccion", "ubicacion", "norma_rectora", "moneda_preferida", "notas")


@app.get("/api/clientes")
async def listar_clientes() -> list[dict[str, Any]]:
    filas = await db.fetch(
        f"SELECT id, {', '.join(_CAMPOS_CLIENTE)}, "
        "(SELECT count(*) FROM proyectos p WHERE p.cliente_id = c.id) AS obras "
        "FROM clientes c ORDER BY nombre"
    )
    return [dict(f) | {"id": str(f["id"])} for f in filas]


@app.post("/api/clientes")
async def crear_cliente(datos: dict[str, Any]) -> dict[str, Any]:
    """Cliente de SOTICA con sus datos habituales; se reutiliza al crear obras."""
    valores = _validar_cliente(_textos(datos))
    try:
        nuevo = await db.fetchval(
            f"INSERT INTO clientes ({', '.join(_CAMPOS_CLIENTE)}) "
            f"VALUES ({', '.join(f'${i}' for i in range(1, len(_CAMPOS_CLIENTE) + 1))}) RETURNING id",
            *valores.values(),
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un cliente con ese nombre o RIF.") from None
    except asyncpg.CheckViolationError as exc:
        raise HTTPException(400, f"Dato inválido: {exc}") from None
    return {"id": str(nuevo), "nombre": valores["nombre"]}


def _validar_cliente(texto) -> dict[str, Any]:
    valores = {c: texto(c) for c in _CAMPOS_CLIENTE}
    if not valores["nombre"]:
        raise HTTPException(400, "La razón social o nombre del cliente es obligatorio.")
    if valores["rif"]:
        rif = re.sub(r"[\s.]", "", valores["rif"].upper())
        m = re.fullmatch(r"([JGVEPC])-?(\d{8})-?(\d)", rif)
        if not m:
            raise HTTPException(400, "RIF inválido: usa el formato J-12345678-9.")
        valores["rif"] = f"{m[1]}-{m[2]}-{m[3]}"
    if valores["tipo_ente"] and valores["tipo_ente"] not in _TIPOS_ENTE:
        raise HTTPException(400, f"Tipo de ente inválido: {valores['tipo_ente']}.")
    if valores["moneda_preferida"] and valores["moneda_preferida"] not in ("USD", "VES"):
        raise HTTPException(400, "La moneda debe ser USD o VES.")
    if valores["correo"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", valores["correo"]):
        raise HTTPException(400, "Correo inválido.")
    return valores


async def _cliente(cliente_id: str):
    try:
        fila = await db.fetchrow("SELECT * FROM clientes WHERE id = $1", UUID(cliente_id))
    except ValueError:
        fila = None
    if fila is None:
        raise HTTPException(404, "Cliente no encontrado.")
    return fila


@app.get("/api/clientes/{cliente_id}")
async def ver_cliente(cliente_id: str) -> dict[str, Any]:
    c = await _cliente(cliente_id)
    obras = await db.fetch(
        "SELECT codigo, nombre_obra, fase FROM proyectos WHERE cliente_id = $1 ORDER BY creado_en DESC",
        c["id"])
    return {k: c[k] for k in _CAMPOS_CLIENTE} | {"id": str(c["id"]), "obras": [dict(o) for o in obras]}


@app.put("/api/clientes/{cliente_id}")
async def editar_cliente(cliente_id: str, datos: dict[str, Any]) -> dict[str, Any]:
    c = await _cliente(cliente_id)
    valores = _validar_cliente(_textos(datos))
    try:
        async with db.transaction() as conn:
            await conn.execute(
                f"UPDATE clientes SET {', '.join(f'{k} = ${i}' for i, k in enumerate(_CAMPOS_CLIENTE, 2))} "
                "WHERE id = $1", c["id"], *valores.values())
            # El nombre visible en las obras es copia del cliente: se mantiene al día.
            await conn.execute("UPDATE proyectos SET cliente = $2 WHERE cliente_id = $1",
                               c["id"], valores["nombre"])
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe otro cliente con ese nombre o RIF.") from None
    except asyncpg.CheckViolationError as exc:
        raise HTTPException(400, f"Dato inválido: {exc}") from None
    return {"id": str(c["id"]), "nombre": valores["nombre"]}


@app.delete("/api/clientes/{cliente_id}")
async def borrar_cliente(cliente_id: str) -> dict[str, Any]:
    c = await _cliente(cliente_id)
    obras = await db.fetchval("SELECT count(*) FROM proyectos WHERE cliente_id = $1", c["id"])
    if obras:
        raise HTTPException(409, f"No se puede borrar: el cliente tiene {obras} proyecto(s). "
                                 "Reasigna o descarta esos proyectos primero.")
    await db.execute("DELETE FROM clientes WHERE id = $1", c["id"])
    return {"ok": True}


@app.post("/api/proyectos")
async def crear_proyecto(datos: dict[str, Any]) -> dict[str, Any]:
    """Alta de obra con su memoria de proyecto (PDF 10.1): moneda, fecha base, ente, norma.
    Con `cliente_id`, lo que no venga en el formulario se toma de los datos del cliente."""
    texto = _textos(datos)
    cliente = None
    if texto("cliente_id"):
        try:
            cliente = await db.fetchrow("SELECT * FROM clientes WHERE id = $1", UUID(texto("cliente_id")))
        except ValueError:
            cliente = None
        if cliente is None:
            raise HTTPException(400, "El cliente seleccionado no existe.")
        for campo, del_cliente in (("tipo_ente", "tipo_ente"), ("ubicacion", "ubicacion"),
                                   ("norma_rectora", "norma_rectora"), ("moneda_base", "moneda_preferida")):
            if not texto(campo) and cliente[del_cliente]:
                datos[campo] = cliente[del_cliente]

    fase = texto("fase") or "oportunidad"
    if fase not in ("oportunidad", "adjudicada"):
        raise HTTPException(400, "Un proyecto nuevo es una oferta en estudio o una obra adjudicada.")
    async with db.acquire() as conn:
        codigo = texto("codigo") or await control.codigo_siguiente(conn)
    nombre = texto("nombre_obra")
    if not nombre:
        raise HTTPException(400, "El nombre del proyecto es obligatorio.")
    if not texto("fecha_base_precios"):
        datos["fecha_base_precios"] = dt.date.today().isoformat()
    tipo_obra = texto("tipo_obra") or "edificacion"
    if tipo_obra not in _TIPOS_OBRA:
        raise HTTPException(400, f"Tipo de obra inválido: {tipo_obra}.")
    tipo_ente = texto("tipo_ente")
    if tipo_ente and tipo_ente not in _TIPOS_ENTE:
        raise HTTPException(400, f"Tipo de ente inválido: {tipo_ente}.")
    moneda = texto("moneda_base") or "USD"
    if moneda not in ("USD", "VES"):
        raise HTTPException(400, "La moneda base debe ser USD o VES.")
    try:
        fechas = {c: dt.date.fromisoformat(datos[c]) if texto(c) else None
                  for c in ("fecha_base_precios", "fecha_inicio_contractual",
                            "fecha_fin_contractual")}
    except ValueError:
        raise HTTPException(400, "Fecha inválida: usa AAAA-MM-DD.") from None
    if fechas["fecha_base_precios"] is None:
        raise HTTPException(400, "La fecha base de precios es obligatoria.")
    try:
        nuevo = await db.fetchval(
            """
            INSERT INTO proyectos (codigo, nombre_obra, cliente_id, cliente, tipo_ente, tipo_obra,
                                   ubicacion, moneda_base, fecha_base_precios, norma_rectora,
                                   fecha_inicio_contractual, fecha_fin_contractual, fase)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id
            """,
            codigo, nombre, cliente["id"] if cliente else None,
            cliente["nombre"] if cliente else texto("cliente"), tipo_ente, tipo_obra,
            texto("ubicacion"), moneda, fechas["fecha_base_precios"], texto("norma_rectora"),
            fechas["fecha_inicio_contractual"], fechas["fecha_fin_contractual"], fase,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, f"Ya existe un proyecto con el código {codigo}.") from None
    except asyncpg.CheckViolationError as exc:
        raise HTTPException(400, f"Dato inválido: {exc}") from None
    return {"id": str(nuevo), "codigo": codigo}


@app.get("/api/proyectos/{ref}/avance-detalle")
async def avance_detalle(ref: str) -> dict[str, Any]:
    """Curva S semanal (plan y real), capítulos, partidas y reportes para la pantalla de avance."""
    p = await _proyecto(ref)
    async with db.acquire() as conn:
        return await control.serie_avance(conn, p["id"])


@app.post("/api/proyectos/{ref}/fase")
async def cambiar_fase(ref: str, datos: dict[str, Any]) -> dict[str, Any]:
    """Decisión humana sobre el ciclo comercial. Adjudicar fija el plazo contractual y, si se
    indica, convierte el presupuesto ofertado en la base de control del avance."""
    p = await _proyecto(ref)
    texto = _textos(datos)
    fase = texto("fase")
    if fase not in ("oportunidad", "adjudicada", "cerrada", "descartada"):
        raise HTTPException(400, "Fase inválida.")
    try:
        inicio = dt.date.fromisoformat(texto("fecha_inicio_contractual")) if texto("fecha_inicio_contractual") else None
        fin = dt.date.fromisoformat(texto("fecha_fin_contractual")) if texto("fecha_fin_contractual") else None
    except ValueError:
        raise HTTPException(400, "Fecha inválida: usa AAAA-MM-DD.") from None
    if inicio and fin and fin < inicio:
        raise HTTPException(400, "El fin contractual no puede ser anterior al inicio.")
    async with db.transaction() as conn:
        await conn.execute(
            """
            UPDATE proyectos SET fase = $2,
                   fecha_inicio_contractual = COALESCE($3, fecha_inicio_contractual),
                   fecha_fin_contractual = COALESCE($4, fecha_fin_contractual)
             WHERE id = $1
            """, p["id"], fase, inicio, fin)
        base = None
        if fase == "adjudicada" and texto("presupuesto_id"):
            pres = await conn.fetchrow("SELECT * FROM presupuestos WHERE id = $1 AND proyecto_id = $2",
                                       UUID(texto("presupuesto_id")), p["id"])
            if pres is None:
                raise HTTPException(404, "Presupuesto no encontrado en este proyecto.")
            await conn.execute("UPDATE presupuestos SET es_base_control = false WHERE proyecto_id = $1", p["id"])
            await conn.execute("UPDATE presupuestos SET es_base_control = true, estado = 'aprobado' WHERE id = $1",
                               pres["id"])
            base = pres["version"]
    return {"codigo": p["codigo"], "fase": fase, "presupuesto_base": base}


@app.get("/api/proyectos/{ref}/estado")
async def estado(ref: str, fecha_corte: str | None = None) -> dict[str, Any]:
    p = await _proyecto(ref)
    corte = dt.date.fromisoformat(fecha_corte) if fecha_corte else dt.date.today()
    async with db.acquire() as conn:
        return await control.estado_obra(conn, p["id"], fecha_corte=corte)


@app.get("/api/proyectos/{ref}/entregables")
async def entregables(ref: str) -> list[dict[str, Any]]:
    p = await _proyecto(ref)
    filas = await db.fetch(
        """
        SELECT e.codigo_documento, e.revision, e.titulo, e.formato, e.generado_por,
               e.formato_oficial, e.creado_en, a.nombre, a.storage_key, a.bytes
          FROM entregables e JOIN archivos a ON a.id = e.archivo_id
         WHERE e.proyecto_id = $1
         ORDER BY e.creado_en DESC
        """,
        p["id"],
    )
    return [dict(f) | {"url": storage.url_for(f["storage_key"])} for f in filas]


@app.get("/api/proyectos/{ref}/bloqueos")
async def bloqueos(ref: str, incluir_resueltos: bool = False) -> dict[str, Any]:
    async with db.acquire() as conn:
        return await avance_mod.consultar_bloqueos(conn, ref, incluir_resueltos)


@app.get("/api/proyectos/{ref}/presupuesto")
async def presupuesto(ref: str, origen: str = "auto") -> dict[str, Any]:
    """Partidas del presupuesto en curso (borrador) o de la base, con sus etiquetas de dato."""
    p = await _proyecto(ref)
    async with db.acquire() as conn:
        pres = await control.presupuesto_por_origen(conn, p["id"], origen)
        if pres is None:
            return {"presupuesto": None, "partidas": []}
        filas = await conn.fetch(
            """
            SELECT pa.codigo_interno, pa.capitulo, pa.descripcion, pa.unidad, pa.cantidad,
                   pa.etiqueta_cantidad, pa.precio_unitario, pa.etiqueta_precio, pa.monto,
                   (SELECT count(*) FROM apu_renglones r WHERE r.partida_id = pa.id) AS renglones_apu,
                   (SELECT count(*) FROM mediciones m WHERE m.partida_id = pa.id) AS mediciones
              FROM partidas pa WHERE pa.presupuesto_id = $1
             ORDER BY pa.capitulo, pa.orden, pa.codigo_interno
            """,
            pres["id"],
        )
    firme = sum(float(f["monto"] or 0) for f in filas
                if f["precio_unitario"] is not None
                and f["etiqueta_precio"] != "pendiente_confirmacion")
    pendiente = sum(float(f["monto"] or 0) for f in filas
                    if f["etiqueta_precio"] == "pendiente_confirmacion")
    return {
        "presupuesto": {"id": str(pres["id"]), "version": pres["version"], "estado": pres["estado"],
                        "es_base_control": pres["es_base_control"], "moneda": pres["moneda"]},
        "partidas": [dict(f) for f in filas],
        "costo_directo_firme": round(firme, 2),
        "monto_pendiente_confirmacion": round(pendiente, 2),
        "indirectos": {"administracion_pct": pres["adm_pct"], "utilidad_pct": pres["utilidad_pct"],
                       "impuesto_pct": pres["impuesto_pct"], "fuente": pres["fuente_indirectos"]},
        "precio_oferta": apu.precio_oferta(firme, pres["adm_pct"], pres["utilidad_pct"],
                                           pres["impuesto_pct"]),
    }


@app.get("/api/proyectos/{ref}/delegaciones")
async def delegaciones(ref: str) -> list[dict[str, Any]]:
    """Anexo "Quién hizo qué" (§5.3): cada delegación de ORQ-COST y lo que usó el subagente."""
    p = await _proyecto(ref)
    filas = await db.fetch(
        """
        SELECT agente_destino, confianza, finalizada_en,
               briefing->>'producto_solicitado' AS producto,
               respuesta->'herramientas_usadas' AS herramientas,
               jsonb_array_length(COALESCE(respuesta->'bloqueos', '[]'::jsonb)) AS bloqueos
          FROM delegaciones WHERE proyecto_id = $1
         ORDER BY iniciada_en DESC LIMIT 30
        """,
        p["id"],
    )
    return [dict(f) for f in filas]


@app.post("/api/proyectos/{ref}/presupuestos/{presupuesto_id}/marcar-base")
async def marcar_base(ref: str, presupuesto_id: str) -> dict[str, Any]:
    """Decisión humana: qué presupuesto es la base contra la que se mide el avance."""
    p = await _proyecto(ref)
    async with db.transaction() as conn:
        pres = await conn.fetchrow(
            "SELECT * FROM presupuestos WHERE id = $1 AND proyecto_id = $2",
            UUID(presupuesto_id), p["id"],
        )
        if pres is None:
            raise HTTPException(404, "Presupuesto no encontrado en esta obra.")
        await conn.execute(
            "UPDATE presupuestos SET es_base_control = false WHERE proyecto_id = $1", p["id"]
        )
        await conn.execute(
            "UPDATE presupuestos SET es_base_control = true, estado = 'aprobado' WHERE id = $1",
            pres["id"],
        )
        return {"ok": True, "version": pres["version"], "es_base_control": True}


# ---------------------------------------------------------------------------
# Evidencia de obra
# ---------------------------------------------------------------------------

@app.post("/api/proyectos/{ref}/reportes")
async def cargar_reporte(
    ref: str,
    reportado_por: str = Form(...),
    fecha_reporte: str = Form(...),
    texto_libre: str = Form(""),
    archivos: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """El residente sube el avance a demanda. Queda CRUDO: nadie lo interpreta aquí.
    SUB-AVA lo procesa cuando el usuario lo pida en el chat."""
    p = await _proyecto(ref)
    async with db.transaction() as conn:
        reporte_id = await conn.fetchval(
            """
            INSERT INTO reportes_avance (proyecto_id, reportado_por, fecha_reporte, canal,
                                         texto_libre)
            VALUES ($1,$2,$3,'panel',$4) RETURNING id
            """,
            p["id"], reportado_por, dt.date.fromisoformat(fecha_reporte), texto_libre or None,
        )
        adjuntos = []
        for f in archivos:
            data = await f.read()
            if not data:
                continue
            key, sha, tam = storage.put_bytes(p["codigo"], f.filename or "evidencia", data)
            archivo_id = await conn.fetchval(
                """
                INSERT INTO archivos (proyecto_id, tipo, nombre, storage_key, mime, bytes,
                                      sha256, subido_por)
                VALUES ($1,'foto_obra',$2,$3,$4,$5,$6,$7) RETURNING id
                """,
                p["id"], f.filename, key, f.content_type or "application/octet-stream",
                tam, sha, reportado_por,
            )
            await conn.execute(
                "INSERT INTO reporte_adjuntos (reporte_id, archivo_id, rol) VALUES ($1,$2,'foto')",
                reporte_id, archivo_id,
            )
            adjuntos.append({"archivo_id": str(archivo_id), "nombre": f.filename})
    return {
        "reporte_id": str(reporte_id),
        "adjuntos": adjuntos,
        "estado": "pendiente",
        "nota": "Reporte cargado sin interpretar. Pídele a ORQ-COST que lo procese.",
    }


@app.get("/api/proyectos/{ref}/planos")
async def listar_planos(ref: str) -> list[dict[str, Any]]:
    p = await _proyecto(ref)
    filas = await db.fetch(
        "SELECT id, nombre, bytes, subido_por, creado_en, storage_key FROM archivos "
        "WHERE proyecto_id = $1 AND tipo = 'plano' ORDER BY creado_en DESC",
        p["id"],
    )
    return [dict(f) for f in filas]


@app.post("/api/proyectos/{ref}/planos")
async def cargar_plano(
    ref: str, subido_por: str = Form(...), archivo: UploadFile = File(...)
) -> dict[str, Any]:
    """Plano en PDF para que SUB-CM lo lea con `leer_plano_pdf`."""
    p = await _proyecto(ref)
    data = await archivo.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "El plano debe ser un PDF.")
    key, sha, tam = storage.put_bytes(p["codigo"], archivo.filename or "plano.pdf", data)
    archivo_id = await db.fetchval(
        """
        INSERT INTO archivos (proyecto_id, tipo, nombre, storage_key, mime, bytes, sha256, subido_por)
        VALUES ($1,'plano',$2,$3,'application/pdf',$4,$5,$6) RETURNING id
        """,
        p["id"], archivo.filename, key, tam, sha, subido_por,
    )
    return {"archivo_id": str(archivo_id), "nombre": archivo.filename}


@app.get("/api/archivos/{storage_key:path}")
async def descargar(storage_key: str):
    ruta = STORAGE_DIR / storage_key
    if not ruta.is_file() or STORAGE_DIR.resolve() not in ruta.resolve().parents:
        raise HTTPException(404, "Archivo no encontrado.")
    return FileResponse(ruta, filename=ruta.name)


# ---------------------------------------------------------------------------
# Chat con ORQ-COST
# ---------------------------------------------------------------------------

def _titulo(mensaje: str) -> str:
    """Título de la conversación: el comienzo del primer mensaje, cortado en una palabra."""
    texto = " ".join(mensaje.split())
    if len(texto) <= 60:
        return texto
    return texto[:60].rsplit(" ", 1)[0] + "…"


async def _conversacion(cid: str):
    try:
        fila = await db.fetchrow(
            "SELECT c.*, p.codigo FROM conversaciones c "
            "LEFT JOIN proyectos p ON p.id = c.proyecto_id WHERE c.id = $1", UUID(cid))
    except ValueError:
        fila = None
    if fila is None:
        raise HTTPException(404, "La conversación no existe.")
    return fila


@app.get("/api/conversaciones")
async def listar_conversaciones() -> list[dict[str, Any]]:
    filas = await db.fetch(
        """
        SELECT c.id, c.titulo, c.actualizado_en, p.codigo, p.nombre_obra, p.fase
          FROM conversaciones c LEFT JOIN proyectos p ON p.id = c.proyecto_id
         ORDER BY c.actualizado_en DESC LIMIT 100
        """
    )
    return [dict(f) for f in filas]


@app.get("/api/conversaciones/{cid}")
async def ver_conversacion(cid: str) -> dict[str, Any]:
    c = await _conversacion(cid)
    return {"id": str(c["id"]), "titulo": c["titulo"], "proyecto": c["codigo"],
            "mensajes": await orchestrator.historial(str(c["id"]))}


@app.patch("/api/conversaciones/{cid}")
async def editar_conversacion(cid: str, datos: dict[str, Any]) -> dict[str, Any]:
    """Mueve la conversación a un proyecto (o la deja general con `proyecto: null`) o la renombra."""
    c = await _conversacion(cid)
    proyecto_id, codigo = c["proyecto_id"], c["codigo"]
    if "proyecto" in datos:
        if datos["proyecto"]:
            p = await _proyecto(datos["proyecto"])
            proyecto_id, codigo = p["id"], p["codigo"]
        else:
            proyecto_id, codigo = None, None
    titulo = " ".join(str(datos.get("titulo") or "").split()) or c["titulo"]
    await db.execute("UPDATE conversaciones SET proyecto_id = $2, titulo = $3 WHERE id = $1",
                     c["id"], proyecto_id, titulo[:120])
    return {"id": str(c["id"]), "titulo": titulo[:120], "proyecto": codigo}


@app.delete("/api/conversaciones/{cid}")
async def borrar_conversacion(cid: str) -> dict[str, Any]:
    """Borra la conversación y su historial. Los datos del proyecto no se tocan."""
    c = await _conversacion(cid)
    await orchestrator.sesion_conversacion(str(c["id"])).clear_session()
    await db.execute("DELETE FROM conversaciones WHERE id = $1", c["id"])
    return {"ok": True}


@app.post("/api/chat")
async def chat(payload: dict[str, Any]):
    """Sin `conversacion`, abre una nueva (con o sin proyecto). El primer evento del stream
    trae su id para que el panel la siga usando."""
    mensaje = (payload.get("mensaje") or "").strip()
    if not mensaje:
        raise HTTPException(400, "Mensaje vacío.")
    if payload.get("conversacion"):
        c = await _conversacion(payload["conversacion"])
        cid, titulo, codigo = c["id"], c["titulo"], c["codigo"]
    else:
        p = await _proyecto(payload["proyecto"]) if payload.get("proyecto") else None
        titulo, codigo = _titulo(mensaje), p["codigo"] if p else None
        cid = await db.fetchval(
            "INSERT INTO conversaciones (proyecto_id, titulo) VALUES ($1, $2) RETURNING id",
            p["id"] if p else None, titulo)
    motor = await _motor_listo()

    async def stream():
        nonlocal codigo
        inicio = {"tipo": "conversacion", "id": str(cid), "titulo": titulo, "proyecto": codigo}
        yield f"data: {json.dumps(inicio, ensure_ascii=False)}\n\n"
        try:
            async for evento in motor.preguntar(mensaje, str(cid), codigo):
                if evento["tipo"] == "proyecto" and not codigo:
                    codigo = evento["codigo"]
                    await db.execute(
                        "UPDATE conversaciones SET proyecto_id = (SELECT id FROM proyectos "
                        "WHERE codigo = $2) WHERE id = $1", cid, codigo)
                yield f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            texto = str(exc)
            if "unsupported_country_region_territory" in texto:
                # OpenAI no atiende desde Venezuela: la salida a internet tiene que ser por otro país.
                texto = ("OpenAI rechazó la conexión por la región de salida a internet. Activa la "
                         "VPN (o usa el servidor fuera de Venezuela) y reintenta el mensaje.")
            yield f"data: {json.dumps({'tipo': 'error', 'texto': texto}, ensure_ascii=False)}\n\n"
        finally:
            await db.execute("UPDATE conversaciones SET actualizado_en = now() WHERE id = $1", cid)

    return StreamingResponse(stream(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="frontend")
