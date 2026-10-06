"""Configuración de entorno del sistema SOTICA-COSTOS."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
AGENTS_DIR = BASE_DIR / "backend" / "agents"


def _cargar_env() -> None:
    """Lee `.env` de la raíz si existe. Las variables ya definidas en el entorno mandan."""
    ruta = BASE_DIR / ".env"
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip("\"'"))


_cargar_env()

# Base de datos (asyncpg para el dominio; SQLAlchemy para la memoria de sesión).
DATABASE_URL = os.getenv(
    "SOTICA_DATABASE_URL",
    "postgresql://sotica:sotica@localhost:5432/sotica",
)


def session_url() -> str:
    """Misma base, driver que SQLAlchemy espera. La memoria de conversación vive
    junto al dominio: una sola base que respaldar."""
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# Bucket de archivos. En ciclo 1 es filesystem local con la misma interfaz
# que usará S3/MinIO más adelante (ver core/storage.py).
STORAGE_DIR = Path(os.getenv("SOTICA_STORAGE_DIR", BASE_DIR / "storage"))
PUBLIC_BASE_URL = os.getenv("SOTICA_PUBLIC_BASE_URL", "http://localhost:8000")

# Modelo del orquestador y de los subagentes. Centralizado aquí a propósito:
# cambiar de modelo no debe implicar tocar los nueve prompts.
MODEL = os.getenv("SOTICA_MODEL", "gpt-5")
# Los subagentes ejecutan tareas acotadas con briefing; pueden ir en un modelo más barato.
MODEL_SUBAGENTES = os.getenv("SOTICA_MODEL_SUBAGENTES") or MODEL

# Si nadie aporta cotización, ORQ-COST puede buscar precios aproximados de materiales en
# internet y registrarlos como referenciales con su enlace. Se apaga con SOTICA_BUSCAR_PRECIOS=0.
BUSCAR_PRECIOS_EN_INTERNET = os.getenv("SOTICA_BUSCAR_PRECIOS", "1") not in ("0", "false", "no")

MAX_TURNS_ORQUESTADOR = int(os.getenv("SOTICA_MAX_TURNS_ORQ", "40"))
MAX_TURNS_SUBAGENTE = int(os.getenv("SOTICA_MAX_TURNS_SUB", "20"))
