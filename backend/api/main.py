"""API HTTP del ciclo 1: chat con ORQ-COST, carga de evidencia y panel de archivos."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..core import avance as avance_mod
from ..core import apu, control, db, storage
from ..core.config import BASE_DIR, STORAGE_DIR
from ..core.orchestrator import SesionObra

app = FastAPI(title="SOTICA-COSTOS", version="ciclo-1")

# Una sesión de chat viva por obra (proceso único; en producción, por usuario).
_sesiones: dict[str, SesionObra] = {}


@app.on_event("shutdown")
async def _cerrar() -> None:
    for s in _sesiones.values():
        await s.cerrar()
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
        SELECT p.id, p.codigo, p.nombre_obra, p.cliente, p.tipo_obra, p.moneda_base,
               eo.pct_fisico_real, eo.pct_fisico_plan, eo.ultima_fecha_avance,
               eo.dias_sin_reporte, eo.bloqueos_abiertos, eo.desviaciones_abiertas
          FROM proyectos p
          LEFT JOIN estado_obra eo ON eo.proyecto_id = p.id
         WHERE p.estado = 'activo'
         ORDER BY p.codigo
        """
    )
    return [dict(f) for f in filas]


_TIPOS_OBRA = {"edificacion", "vialidad", "hidraulica", "electrificacion", "industrial"}
_TIPOS_ENTE = {"publico_nacional", "publico_estadal", "publico_municipal", "privado",
               "multilateral"}


@app.post("/api/proyectos")
async def crear_proyecto(datos: dict[str, Any]) -> dict[str, Any]:
    """Alta de obra con su memoria de proyecto (PDF 10.1): moneda, fecha base, ente, norma."""
    def texto(campo: str) -> str | None:
        valor = str(datos.get(campo) or "").strip()
        return valor or None

    codigo, nombre = texto("codigo"), texto("nombre_obra")
    if not codigo or not nombre:
        raise HTTPException(400, "Código y nombre de la obra son obligatorios.")
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
            INSERT INTO proyectos (codigo, nombre_obra, cliente, tipo_ente, tipo_obra, ubicacion,
                                   moneda_base, fecha_base_precios, norma_rectora,
                                   fecha_inicio_contractual, fecha_fin_contractual)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id
            """,
            codigo, nombre, texto("cliente"), tipo_ente, tipo_obra, texto("ubicacion"), moneda,
            fechas["fecha_base_precios"], texto("norma_rectora"),
            fechas["fecha_inicio_contractual"], fechas["fecha_fin_contractual"],
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, f"Ya existe una obra con el código {codigo}.") from None
    except asyncpg.CheckViolationError as exc:
        raise HTTPException(400, f"Dato inválido: {exc}") from None
    return {"id": str(nuevo), "codigo": codigo}


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
        "presupuesto": {"version": pres["version"], "estado": pres["estado"],
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

@app.post("/api/chat")
async def chat(payload: dict[str, Any]):
    proyecto_ref = payload.get("proyecto")
    mensaje = (payload.get("mensaje") or "").strip()
    if not mensaje:
        raise HTTPException(400, "Mensaje vacío.")

    clave = proyecto_ref or "_sin_obra"
    if clave not in _sesiones:
        sesion = SesionObra(proyecto_ref)
        await sesion.abrir()
        _sesiones[clave] = sesion
    sesion = _sesiones[clave]

    async def stream():
        try:
            async for evento in sesion.preguntar(mensaje):
                yield f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            texto = str(exc)
            if "unsupported_country_region_territory" in texto:
                # OpenAI no atiende desde Venezuela: la salida a internet tiene que ser por otro país.
                texto = ("OpenAI rechazó la conexión por la región de salida a internet. Activa la "
                         "VPN (o usa el servidor fuera de Venezuela) y reintenta el mensaje.")
            yield f"data: {json.dumps({'tipo': 'error', 'texto': texto}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.delete("/api/chat/{ref}")
async def reiniciar_chat(ref: str) -> dict[str, Any]:
    """Conversación nueva para la obra: olvida el historial del chat, no los datos."""
    sesion = _sesiones.pop(ref, None) or SesionObra(ref)
    await sesion.reiniciar()
    await sesion.cerrar()
    return {"ok": True}


app.mount("/", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="frontend")
