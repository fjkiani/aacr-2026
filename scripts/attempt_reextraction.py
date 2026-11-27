#!/usr/bin/env python3
"""Thin CLI — prioritized re-extraction stubs / API prep."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aacr_corpus.cli import reextract_main

if __name__ == "__main__":
    reextract_main()
