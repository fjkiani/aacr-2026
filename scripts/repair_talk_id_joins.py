#!/usr/bin/env python3
"""Thin CLI — logic lives in aacr_corpus.identity / schema_b_clean / cli."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aacr_corpus.cli import repair_main

if __name__ == "__main__":
    repair_main()
