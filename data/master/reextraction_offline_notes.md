# Offline re-extraction stubs

Generated: `2026-11-27T22:46:24.907636+00:00`

No LLM API keys detected (`OPENROUTER_KEY_*` / `OPENROUTER_API_KEY`).
Wrote **10** session stubs under `data/master/reextraction_stubs/` for the top prioritized queue items.

## Stub contents

- Current Schema A/B JSON (if present)
- Queue metadata (reason, unmatched speakers, action)
- Extractor guidance (patched v6 speaker paths + orphan filter)

## Top stubs

- `leveraging-nci-supported-cancer-epidemiology-cohorts-to-advance-cancer-preventio.stub.json` — `no_schema_a` / `extract_schema_a_missing` (5 unmatched B)
- `nci-opportunities-to-support-early-career-cancer-researchers-and-research-specia.stub.json` — `no_schema_a` / `extract_schema_a_missing` (4 unmatched B)
- `nci-opportunities-in-technology-development-for-cancer-research.stub.json` — `no_schema_a` / `extract_schema_a_missing` (3 unmatched B)
- `researcher-town-hall-navigating-policy-challenges-and-securing-funding.stub.json` — `no_schema_a` / `extract_schema_a_missing` (3 unmatched B)
- `aacr-margaret-foti-award-for-leadership-and-extraordinary-achievements-in-cancer.stub.json` — `no_schema_a` / `extract_schema_a_missing` (1 unmatched B)
- `cracking-adaptive-resistance-ai-enabled-screen-guided-targets-in-tumor-plasticit.stub.json` — `asr_name` / `reextract_or_manual_asr_resolve` (2 unmatched B)
- `combating-t-cell-checkpoints.stub.json` — `count_mismatch` / `reextract_aligned_ab` (4 unmatched B)
- `cancer-prevention-and-screening-exploring-policy-solutions.stub.json` — `count_mismatch` / `reextract_aligned_ab` (2 unmatched B)
- `contextual-challenges-in-interpreting-performance-of-blood-based-early-cancer-de.stub.json` — `count_mismatch` / `reextract_aligned_ab` (2 unmatched B)
- `improving-cancer-outcomes-by-shaping-the-tumor-macroenvironment.stub.json` — `count_mismatch` / `reextract_aligned_ab` (2 unmatched B)

When keys are available: run `python3 scripts/attempt_reextraction.py --limit N` to attempt limited live re-extract of top queue sessions.
