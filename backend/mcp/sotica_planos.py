"""Servidor MCP `sotica_planos` — lectura de planos en PDF.

Ciclo 1.5: cubre `leer_plano_pdf` que SUB-CM necesita para computar a partir de
planos. No hace criterio de ingeniería: solo extrae texto + dimensiones /
diámetros / áreas detectadas por regex, y devuelve la lista de páginas.

El contrato es deliberadamente conservador: si una medida no aparece
explícitamente en el PDF, no se devuelve. SUB-CM sigue siendo responsable de
validar contra el plano físico o pedir aclaración al residente.
"""
from __future__ import annotations

import io
import re
from typing import Any

import pypdf

from ..core import control, db, storage
from .registry import Registro, error as _error, ok as _ok

registro = Registro("sotica_planos")


_RE_LINEAL = re.compile(r"\b\d+[.,]\d+\s*(mm|cm|m)\b", re.IGNORECASE)
_RE_DIAMETRO = re.compile(
    r"(?:[Øø]|\bD)\s*\d+(?:[.,]\d+)?\s*(?:\"|(?:mm|pulg(?:adas?)?|in)\b)", re.IGNORECASE)
_RE_AREA = re.compile(r"\b\d+[.,]\d+\s*m\s*[²2]\b", re.IGNORECASE)
_RE_VOLUMEN = re.compile(r"\b\d+[.,]\d+\s*m\s*[³3]\b", re.IGNORECASE)
_RE_TITULO = re.compile(r"(?im)^\s*(PROYECTO|ESCALA|FECHA|L[ÁA]MINA|LAMINA|HOJA|REV(?:ISI[ÓO]N)?)\s*[:：]\s*(.+)$")
_RE_NOTA = re.compile(r"(?im)^\s*NOTA(?:S)?\s*[:：\-]\s*(.+)$")


# ponytail: tope fijo por página para no llenar el contexto del modelo; paginar si hay láminas densas.
_MAX_TEXTO_PAGINA = 6000


def _parsear_pdf(data: bytes, max_paginas: int) -> dict[str, Any]:
    reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
    total = len(reader.pages)
    paginas = []
    todo_texto: list[str] = []
    for i in range(min(total, max_paginas)):
        try:
            txt = reader.pages[i].extract_text() or ""
        except Exception:  # noqa: BLE001
            txt = ""
        todo_texto.append(txt)
        paginas.append({"numero": i + 1, "texto": txt[:_MAX_TEXTO_PAGINA],
                        "texto_truncado": len(txt) > _MAX_TEXTO_PAGINA})

    texto = "\n".join(todo_texto)
    lineales = sorted({m.group(0).strip()
                       for m in _RE_LINEAL.finditer(texto)})
    diametros = sorted({m.group(0).strip()
                         for m in _RE_DIAMETRO.finditer(texto)})
    areas = sorted({m.group(0).strip()
                    for m in _RE_AREA.finditer(texto)})
    volumenes = sorted({m.group(0).strip()
                        for m in _RE_VOLUMEN.finditer(texto)})

    title_block: dict[str, str] = {}
    for m in _RE_TITULO.finditer(texto):
        clave = m.group(1).upper().replace("Á", "A").replace("Ó", "O").rstrip(":")
        title_block[clave] = m.group(2).strip()
    notas = [m.group(1).strip() for m in _RE_NOTA.finditer(texto)]

    advertencia = []
    if total > max_paginas:
        advertencia.append(
            f"El plano tiene {total} páginas y se procesaron solo las primeras "
            f"{max_paginas}. Si necesitas información de páginas posteriores, "
            "vuelve a llamar la herramienta con un max_paginas mayor."
        )
    if not lineales and not diametros and not areas:
        advertencia.append(
            "No se detectaron cotas ni dimensiones con los patrones habituales. "
            "El PDF podría ser un escaneo sin capa de texto: pide al residente "
            "el plano en formato vectorial o las cotas transcritas."
        )

    return {
        "paginas_procesadas": len(paginas),
        "paginas_totales": total,
        "title_block": title_block,
        "paginas": paginas,
        "dimensiones_lineales_detectadas": lineales,
        "diametros_detectados": diametros,
        "areas_detectadas": areas,
        "volumenes_detectados": volumenes,
        "notas_del_plano": notas[:20],
        "advertencia_datos": advertencia,
    }


@registro.herramienta(
    "listar_planos",
    "Lista los planos, pliegos y especificaciones cargados para una obra, con su "
    "archivo_id. Llámala antes de leer_plano_pdf para saber qué documentos existen.",
    {
        "type": "object",
        "properties": {
            "proyecto": {"type": "string", "description": "uuid o código de obra (SOT-2026-014)"},
        },
        "required": ["proyecto"],
    },
)
async def listar_planos(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with db.acquire() as conn:
            proyecto = await control.proyecto_por_ref(conn, args["proyecto"])
            if proyecto is None:
                return _error(f"No existe la obra '{args['proyecto']}'.")
            filas = await conn.fetch(
                "SELECT id, nombre, tipo, bytes, subido_por, creado_en FROM archivos "
                "WHERE proyecto_id = $1 AND tipo IN ('plano','pliego','especificacion') "
                "ORDER BY creado_en DESC",
                proyecto["id"],
            )
        return _ok({
            "obra": proyecto["codigo"],
            "planos": [dict(f) | {"archivo_id": str(f["id"])} for f in filas],
            "nota": "Sin planos cargados: pide al usuario que suba el PDF en el panel "
                    "(pestaña Archivos) o que transcriba las cotas." if not filas else None,
        })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


@registro.herramienta(
    "leer_plano_pdf",
    "Lee un plano PDF almacenado en el bucket de la obra y devuelve su contenido "
    "extractable: title block, texto de cada página (rótulos, cotas, cuadros), y "
    "las cotas lineales, diámetros, áreas y notas detectadas. "
    "Solo lo que aparece literalmente en el texto del PDF — sin OCR ni criterio de "
    "ingeniería. Si un valor no se detecta, NO se devuelve: el agente debe pedirlo "
    "explícitamente al residente. Usada por SUB-CM para alimentar cómputos.",
    {
        "type": "object",
        "properties": {
            "archivo_id": {"type": "string",
                           "description": "uuid del archivo en la tabla `archivos`"},
            "max_paginas": {"type": "integer", "default": 50,
                            "description": "tope de páginas a procesar"},
        },
        "required": ["archivo_id"],
    },
)
async def leer_plano_pdf(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with db.acquire() as conn:
            arch = await conn.fetchrow(
                "SELECT id, proyecto_id, nombre, tipo, storage_key, mime "
                "FROM archivos WHERE id = $1",
                args["archivo_id"],
            )
        if arch is None:
            return _error(f"No existe el archivo '{args['archivo_id']}'.")
        if arch["tipo"] not in ("plano", "pliego", "especificacion"):
            return _error(
                f"El archivo '{arch['nombre']}' es de tipo '{arch['tipo']}', "
                "no se procesa como plano. Usa esta herramienta con archivos de "
                "tipo 'plano', 'pliego' o 'especificacion'."
            )
        try:
            data = storage.read_bytes(arch["storage_key"])
        except FileNotFoundError:
            return _error(
                f"El binario del plano no está en el bucket (storage_key={arch['storage_key']})."
            )
        try:
            extraido = _parsear_pdf(data, int(args.get("max_paginas") or 50))
        except Exception as exc:  # noqa: BLE001
            return _error(f"No se pudo parsear el PDF: {exc}")
        return _ok({
            "archivo": {
                "id": str(arch["id"]),
                "nombre": arch["nombre"],
                "tipo": arch["tipo"],
                "mime": arch["mime"],
            },
            **extraido,
            "nota": (
                "Solo se devolvieron medidas explícitas en el texto del PDF. "
                "Si falta información, decláralo como faltante — no la asumas."
            ),
        })
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


__all__ = ["registro"]