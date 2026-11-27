# Fix Plan — What’s Broken & How to Repair It

**Companion to:** `reports/vectorization_ml_audit.md`  
**Repair script:** `scripts/repair_talk_id_joins.py`  
**Triage:** `scripts/triage_unmatched_talks.py` → `data/master/unmatched_talk_triage.csv`  
**Flywheel:** `scripts/recompute_flywheel_quality.py`  
**Embedding units (offline):** `scripts/build_embedding_units.py` → `data/embeddings/`

---

## Root cause (identity)

Schema A/B `talk_id` join was not a fuzzy data problem — it was a **post-processor bug**.

In `extractor_v3`–`v6`, after LLM extraction:

```python
last = rec.get("speaker", {}).get("name", "unknown").split()[-1].lower()
rec["talk_id"] = f"{slug}::{last}::{i+1}"
```

| Schema | Where speaker lives | Result |
|---|---|---|
| A | `speaker.name` | Correct `slug::lastname::N` |
| B | `talk_metadata.speaker_name` | Always `slug::unknown::N` |

Evidence: **837 / 926** Schema B rows had a real speaker name in metadata but `::unknown::` in `talk_id`. Only **22** exact A↔B ID matches before repair.

Secondary bug: JSON parse sometimes promoted nested objects into the top-level Schema B array. Worst case: `advances-in-therapeutic-antibodies` → **47** “rows”, only **2** valid talks (**45 orphan fragments**).

---

## Fix 1 — Identity repair

### Done (this PR)

```bash
python3 scripts/repair_talk_id_joins.py --write
python3 scripts/triage_unmatched_talks.py
```

Cascade v2: **name → fuzzy ASR last-name (≥0.72) → first-name → name+title → title/token → equal-count order → shift-aware residual**.

| Metric | Pre-repair | After v1 filter+join | After v2 cascade |
|---|---|---|---|
| Exact talk_id matches | 22 | — | — |
| Orphan fragments | 45 | 0 | 0 |
| Valid B joined to A | — | **806 / 881 (91.5%)** | **810 / 881 (91.9%)** |
| Of joinable (has Schema A) | — | 806 / 865 (93.2%) | **810 / 865 (93.6%)** |
| Schema B `::unknown::` talk_ids | 891 / 926 | 5 / 881 | **5 / 881** |
| Unmatched B | — | 75 | **71** |

Recovered offline examples: Eva Hernando↔Monje, Ghulam Rasul↔Rasool, Gadi↔Getz, Patrick↔Dugan.

### Residual unmatched (71 talks / 47 sessions)

Triage categories (`data/master/unmatched_talk_triage.csv`):

| Category | Count | Notes |
|---|---|---|
| `count_mismatch` | 49 | B extracted extra chairs/panelists A never modeled |
| `no_schema_a` | 16 | 5 sessions with B only — **blocked without Schema A extract** |
| `low_signal` | 4 | Speaker N / panel / no original data |
| `asr_name` | 2 | Leftover A still needs human/LLM name resolve |

Queue + notes: `data/master/reextraction_queue.csv`, `data/master/reextraction_queue_notes.md`.

**Blocked without LLM / Schema A (5 sessions):**
- `leveraging-nci-supported-cancer-epidemiology-cohorts-to-advance-cancer-preventio`
- `nci-opportunities-to-support-early-career-cancer-researchers-and-research-specia`
- `nci-opportunities-in-technology-development-for-cancer-research`
- `researcher-town-hall-navigating-policy-challenges-and-securing-funding`
- `aacr-margaret-foti-award-for-leadership-and-extraordinary-achievements-in-cancer`

≥95% of all valid B (837/881) needs those Schema A fills + ~12 more aligned re-extracts. Offline ceiling without new A rows ≈ **93.6% of joinable**.

### Permanent (extractor)
`extractor_v6.py` now reads `speaker.name` **or** `talk_metadata.speaker_name` and filters Schema B before reindexing.

---

## Fix 2 — Stop embedding junk (offline units ready)

```bash
python3 scripts/build_embedding_units.py
```

Emits claim-level JSONL under `data/embeddings/` (see `data/embeddings/README.md`).

| Unit type | Count (gated) |
|---|---|
| talk_card | 858 |
| clinical_fact | 1,480 |
| crispro_opp | 1,752 |
| cd_hit | 461 |
| vulnerability | 671 |
| **total** | **5,222** |

Gates: resolvable non-`::unknown::` talk_id for intel units; entity anchor; evidence/quote/value present. Quarantines unknown-speaker low-signal cards.

**Not done:** Supabase re-index / `match_embeddings` RPC (auth declined). Load `data/embeddings/*.jsonl` when credentials available.

---

## Fix 3 — Flywheel / ML data quality

```bash
python3 scripts/recompute_flywheel_quality.py
```

| Broken | Fix status |
|---|---|
| All SFT `quality_score = 0.85` | **Done** → gated scores in `data/flywheel/aacr_flywheel_seed_scored.json` (8 unique values, mean 0.934, range 0.60–0.95). Summary: `reports/flywheel_quality_summary.md` |
| All 450 rejected prefs = `fast_path_no_cd_analysis` stubs | **Done** → synthetic failure modes: hallucinated_opp (113), missing_quote (113), wrong_talk_id (112), empty_arrays_on_rich_talk (112) |
| Extractor/B split | Train next SFT gen on **repaired** joined pairs (still open) |

Model build order stays: **reranker → extractor LoRA/DPO → fit ranker**; still do not train a custom embedder on this scale.

---

## Fix 4 — Downstream consumers (still open)

After remap + re-embed:

1. `match_embeddings` RPC — filter by `source_type`, lower threshold for short clinical facts
2. `aacr-semantic-search` / `crispro-scorer` / `cd-hit-extractor` — join on repaired `talk_id`
3. CRM push — only rows with `joined=yes` + priority high/medium

---

## Execution order

1. **Done:** root-cause analysis, `repair_talk_id_joins.py`, extractor_v6 guard, join map
2. **Done:** `--write` repaired Schema B + remapped masters
3. **Done:** triage `joined=no` + re-extraction queue (LLM re-pass still open / blocked for 5 sessions)
4. **Done:** flywheel quality scores + real DPO rejects (offline/synthetic)
5. **Done offline:** claim-unit JSONL builder; **open:** Supabase embed + hybrid RPC
6. **Open:** gold-set eval (Recall@10 / entity hit-rate) before/after

---

## Success criteria

- [x] Schema B `::unknown::` rate &lt; 5% (5/881 ≈ 0.6%)
- [ ] A↔B join coverage ≥ 95% of valid B talks (**91.9%** all / **93.6%** joinable — blocked on missing Schema A)
- [x] Zero orphan fragments in Schema B arrays
- [x] Offline embedding units require resolvable `talk_id` (intel units)
- [x] Flywheel quality scores non-constant
- [ ] Search gold-set entity hit-rate improves vs pre-repair baseline (needs Supabase)
- [x] Preference rejects are real failure modes (not stub-only)
