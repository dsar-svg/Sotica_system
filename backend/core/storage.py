"""Bucket de archivos.

Ciclo 1: filesystem local. La interfaz (put/open/url) es la que usará S3/MinIO,
así que cambiar de backend no toca a los agentes ni a las herramientas MCP.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from .config import PUBLIC_BASE_URL, STORAGE_DIR


def _path_for(storage_key: str) -> Path:
    return STORAGE_DIR / storage_key


def put_bytes(proyecto_codigo: str, nombre: str, data: bytes) -> tuple[str, str, int]:
    """Guarda el binario y devuelve (storage_key, sha256, bytes)."""
    sufijo = Path(nombre).suffix or ".bin"
    storage_key = f"{proyecto_codigo}/{uuid.uuid4().hex}{sufijo}"
    destino = _path_for(storage_key)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(data)
    return storage_key, hashlib.sha256(data).hexdigest(), len(data)


def read_bytes(storage_key: str) -> bytes:
    return _path_for(storage_key).read_bytes()


def url_for(storage_key: str) -> str:
    return f"{PUBLIC_BASE_URL}/api/archivos/{storage_key}"
