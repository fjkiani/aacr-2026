# Flywheel quality rescoring summary

Source: `data/flywheel/aacr_flywheel_seed.json`  
Output: `data/flywheel/aacr_flywheel_seed_scored.json`

## SFT quality_score

- Rows: **862**
- Unique scores (was 1×0.85): **8**
- Mean: **0.9337**
- Min / max: **0.6000** / **0.9500**

### Distribution

| Score | Count |
|---|---|
| 0.95 | 638 |
| 0.90 | 195 |
| 0.85 | 13 |
| 0.80 | 11 |
| 0.75 | 1 |
| 0.70 | 2 |
| 0.65 | 1 |
| 0.60 | 1 |

### Gate pass rates

| Gate | Pass | Rate |
|---|---|---|
| `parse_complete` | 862 | 100.0% |
| `moa_present` | 862 | 100.0% |
| `moa_substantive` | 860 | 99.8% |
| `findings_present` | 861 | 99.9% |
| `findings_rich` | 845 | 98.0% |
| `talk_id_resolvable` | 853 | 99.0% |
| `entity_anchor` | 860 | 99.8% |
| `speaker_known` | 858 | 99.5% |
| `stage_specified` | 657 | 76.2% |
| `evidence_quote` | 0 | 0.0% |

## Preference rejects

- Regenerated: **450** (was all `fast_path_no_cd_analysis`)

| Failure mode | Count |
|---|---|
| `hallucinated_opp` | 113 |
| `missing_quote` | 113 |
| `wrong_talk_id` | 112 |
| `empty_arrays_on_rich_talk` | 112 |

Rejects are synthetic/offline transformations of the chosen response — no LLM API used.
