#!/usr/bin/env python3
"""Thin CLI — logic lives in aacr_corpus.flywheel_quality / cli."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aacr_corpus.cli import flywheel_main

if __name__ == "__main__":
    flywheel_main()
