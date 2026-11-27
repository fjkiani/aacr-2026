"""Shared filesystem paths for the AACR corpus package."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR_A = ROOT / "extractions" / "schema_a"
DIR_B = ROOT / "extractions" / "schema_b"
MASTER = ROOT / "data" / "master"
FLYWHEEL = ROOT / "data" / "flywheel"
EMBEDDINGS = ROOT / "data" / "embeddings"
REPORTS = ROOT / "reports"
REEXTRACT_STUBS = MASTER / "reextraction_stubs"
