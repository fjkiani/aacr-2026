#!/usr/bin/env python3
"""Thin CLI — logic lives in aacr_corpus.triage / reextract / cli."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aacr_corpus.cli import triage_main

if __name__ == "__main__":
    triage_main()
