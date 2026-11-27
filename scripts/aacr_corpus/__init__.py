"""
AACR corpus repair / triage / flywheel / embedding package.

Module map
----------
paths              Shared ROOT / MASTER / extraction dirs
identity           Name/title similarity, talk_id rewrite, cascade join
schema_b_clean     Orphan fragment filter + Schema B field accessors
triage             Unmatched B categorization + re-extraction queue rows
flywheel_quality   SFT score gates + synthetic preference rejects
embedding_units    Claim-level unit builders (joined + provisional/unmatched)
reextract          Prioritized re-extraction (API if keys present, else stubs)
cli                Argparse entrypoints used by thin scripts/* wrappers
"""

__all__ = [
    "paths",
    "identity",
    "schema_b_clean",
    "triage",
    "flywheel_quality",
    "embedding_units",
    "reextract",
    "cli",
]
