"""Configuración de entorno del sistema SOTICA-COSTOS."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
AGENTS_DIR = BASE_DIR / "backend" / "agents"

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

MAX_TURNS_ORQUESTADOR = int(os.getenv("SOTICA_MAX_TURNS_ORQ", "40"))
MAX_TURNS_SUBAGENTE = int(os.getenv("SOTICA_MAX_TURNS_SUB", "20"))

# Agentes habilitados en el ciclo 1. El resto está escrito en backend/agents/
# con `enabled: false` en su frontmatter y no se registra en la sesión.
CICLO_1_AGENTES = {"SUB-CM", "SUB-DOC", "SUB-AVA"}
