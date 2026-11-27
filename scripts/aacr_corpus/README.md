# `aacr_corpus` — modular AACR repair / index prep

Gutted from one-file scripts into focused modules. Thin wrappers under `scripts/`
keep the old entrypoint names working.

## Module map

| Module | Responsibility |
|---|---|
| `paths.py` | `ROOT`, `MASTER`, extraction + embedding dirs |
| `identity.py` | Name/title sim, `talk_id` rewrite, cascade join |
| `schema_b_clean.py` | Orphan fragment filter + A/B field accessors |
| `triage.py` | Unmatched categorization + prioritized queue |
| `flywheel_quality.py` | SFT score gates + synthetic preference rejects |
| `embedding_units.py` | Claim unit builders; **joined + unmatched + provisional** |
| `reextract.py` | Top-queue stubs; optional API prep if keys exist |
| `cli.py` | Argparse entrypoints |

## Entrypoints (compatible)

```bash
python3 scripts/repair_talk_id_joins.py [--write]
python3 scripts/triage_unmatched_talks.py [--stubs 10]
python3 scripts/recompute_flywheel_quality.py
python3 scripts/build_embedding_units.py [--joined-only]
python3 scripts/attempt_reextraction.py [--limit 10]
```

## Beyond joinables

`build_embedding_units.py` no longer treats “joined to Schema A” as the ceiling:

- Unmatched B intel (CrisPRO / CD / vuln) → `metadata.join_status=unmatched`
- B-only sessions (no Schema A) → `join_status=provisional` + synthesized talk cards
- Quality flags: `has_evidence`, `has_entity`, `provisional`, `indexable`

Use `--joined-only` for the legacy gate behavior.
