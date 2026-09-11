"""API HTTP del ciclo 1: chat con ORQ-COST, carga de evidencia y panel de archivos."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..core import avance as avance_mod
from ..core import control, db, storage
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
            yield f"data: {json.dumps({'tipo': 'error', 'texto': str(exc)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="frontend")
