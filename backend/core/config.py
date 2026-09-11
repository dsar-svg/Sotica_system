"""Configuración de entorno del sistema SOTICA-COSTOS."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
AGENTS_DIR = BASE_DIR / "backend" / "agents"

# Base de datos
DATABASE_URL = os.getenv(
    "SOTICA_DATABASE_URL",
    "postgresql://sotica:sotica@localhost:5432/sotica",
)

# Bucket de archivos. En ciclo 1 es filesystem local con la misma interfaz
# que usará S3/MinIO más adelante (ver core/storage.py).
STORAGE_DIR = Path(os.getenv("SOTICA_STORAGE_DIR", BASE_DIR / "storage"))
PUBLIC_BASE_URL = os.getenv("SOTICA_PUBLIC_BASE_URL", "http://localhost:8000")

# Modelo del orquestador y de los subagentes.
MODEL = os.getenv("SOTICA_MODEL", "claude-opus-5")

# Agentes habilitados en el ciclo 1. El resto está escrito en backend/agents/
# con `enabled: false` en su frontmatter y no se registra en la sesión.
CICLO_1_AGENTES = {"SUB-CM", "SUB-DOC", "SUB-AVA"}
