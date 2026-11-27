#!/usr/bin/env python3
"""Thin CLI — logic lives in aacr_corpus.embedding_units / cli."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aacr_corpus.cli import embeddings_main

if __name__ == "__main__":
    embeddings_main()
