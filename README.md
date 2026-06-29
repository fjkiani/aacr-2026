# AACR 2026 — Intelligence Corpus

Extracted, structured, and embedded intelligence from AACR Annual Meeting 2026.

## What's Here

### `transcripts/`
- `txt/` — 272 cleaned plain-text transcripts (one per session)
- `vtt/` — 272 raw WebVTT caption files

### `extractions/`
- `schema_a/` — 264 Schema A extractions: scientific content (speaker, institution, drug, target, trial data, data maturity, clinical readout)
- `schema_b/` — 266 Schema B extractions: competitive intelligence (CrisPRO opportunities, cognitive dissonance hits, vulnerability analysis)

### `manifests/`
272 per-session manifest JSONs linking transcript → schema_a → schema_b extractions.

### `data/master/`
Aggregated outputs across all sessions:

| File | Description |
|---|---|
| `schema_a_master.json` / `.csv` | All Schema A records (862 speakers) |
| `schema_b_master.json` / `.csv` | All Schema B records (926 competitive intel rows) |
| `sessions.csv` / `.jsonl` | Session index (296 sessions) |
| `clinical_data_all.csv` | 1,480 clinical data entries |
| `cognitive_dissonance_all.csv` | Cognitive dissonance hits |
| `crispro_opportunities_all.csv` | CrisPRO-scored opportunities |
| `trial_references_named.csv` | Named trial references |
| `nct_candidates_unverified.csv` | Candidate NCT numbers (unverified) |
| `nct_numbers_UNVERIFIED.csv` | Raw NCT number extractions |
| `audit_report.md` | Extraction quality audit |
| `schema_a_scientific.json` | Schema A field definitions |
| `schema_b_competitive_intel.json` | Schema B field definitions |

### `data/flywheel/`
- `aacr_flywheel_seed.json` — 862 SFT rows + 450 preference pairs for the double-dip flywheel (`competitive_intel_extraction` task type). Loaded into Render Postgres `zie_training_records` + `zie_preference_pairs`.

### `data/`
- `run_log_v4/v5/v6.jsonl` — Extractor run logs
- `run_results.jsonl` — Per-session extraction results
- `battle_test_results.json` — Schema battle-test output
- `schema_b_hits.jsonl` — Schema B hit stream

### `scripts/`
- `extractor_v3.py` through `extractor_v6.py` — Iterative extractor pipeline versions. v6 is production.

## Scale

| Metric | Count |
|---|---|
| Sessions processed | 296 |
| Transcripts | 272 |
| Schema A extractions | 264 |
| Schema B extractions | 266 |
| Speakers indexed | 862 |
| Competitive intel rows | 926 |
| Clinical data entries | 1,480 |
| Embeddings (Supabase) | 3,024 |
| SFT flywheel rows | 862 |
| Preference pairs | 450 |

## Supabase

Live corpus is embedded and indexed in Supabase project `xfhiwodulrbbtfcqneqt`:
- `aacr_sessions` (296 rows)
- `aacr_speakers` (862 rows)
- `aacr_competitive_intel` (926 rows)
- `aacr_clinical_data` (1,480 rows)
- `aacr_embeddings` (3,024 rows, IVFFlat index `lists=100`)

Semantic search via `match_embeddings` RPC (cosine similarity, threshold 0.65).

## Integration

The AACR corpus is the data layer for the **"Conference Intelligence → CRM Pipeline"** workflow in `fjkiani/openclaw-saas`. Skill handlers:
- `aacr-semantic-search` — embed query → `match_embeddings` RPC → speaker records
- `crispro-scorer` — fetch `aacr_crispro_opps` view for matched talk_ids
- `cd-hit-extractor` — fetch `aacr_cd_hits` view for matched talk_ids
- `crm-push` — stub (pending Crunchbase/HubSpot connector)
