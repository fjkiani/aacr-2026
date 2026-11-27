# Fix Plan — What’s Broken & How to Repair It

**Companion to:** `reports/vectorization_ml_audit.md`  
**Repair script:** `scripts/repair_talk_id_joins.py`

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

Evidence: **837 / 926** Schema B rows have a real speaker name in metadata but `::unknown::` in `talk_id`. Only **22** exact A↔B ID matches before repair.

Secondary bug: JSON parse sometimes promoted nested objects into the top-level Schema B array. Worst case: `advances-in-therapeutic-antibodies` → **47** “rows”, only **2** valid talks (**45 orphan fragments**).

---

## Fix 1 — Identity repair (do this first)

### Immediate (offline, no re-extract)
Run:

```bash
python3 scripts/repair_talk_id_joins.py --write
```

What it does:
1. Drops orphan non-talk Schema B fragments
2. Cascade-joins B→A: **name → name+title → title → equal-count order**
3. Rewrites B `talk_id` to the canonical Schema A id when joined
4. Writes `data/master/talk_id_join_map.csv`
5. Remaps `schema_b_master.*`, `crispro_opportunities_all.csv`, `cognitive_dissonance_all.csv`

### Measured recovery (dry-run on current corpus)

| Metric | Before | After filter+join |
|---|---|---|
| Exact talk_id matches | 22 | — |
| Orphan fragments | 45 (1 session) | 0 dropped |
| Valid B joined to A | — | **806 / 865 (93.2%)** |
| Unmatched B | — | ~59 |
| Unmatched A | — | ~52 |

Join methods: mostly unique last-name (~764), then title (~32), name+title (~3), order (~7).

### Permanent (extractor)
`extractor_v6.py` now:
- Reads `speaker.name` **or** `talk_metadata.speaker_name`
- Filters Schema B to records that have talk metadata before reindexing

Re-extract only needed for unmatched / low-signal sessions, not the full 272.

### Residual unmatched (~7%)
Handle as a triage queue from `talk_id_join_map.csv` where `joined=no`:
- Count-mismatched sessions (79 before filter; fewer after)
- ASR name garbling (`Adelsten` vs `Adel`, first-name-only speakers)
- Schema A/B disagreed on who “presented data”

Action: human or LLM re-pass those sessions with both schemas in one call so IDs are assigned together.

---

## Fix 2 — Stop embedding junk

Once IDs are repaired:

| Do | Don’t |
|---|---|
| Embed talk cards (MOA + findings + targets) | Embed raw ~76k-char transcripts |
| Embed clinical facts / CrisPRO / CD units with evidence | Embed empty intel arrays (73 low-signal B rows) |
| Hybrid BM25 (gene/drug/NCT) + dense + rerank | Global cosine 0.65 only |
| Require resolvable `talk_id` + entity anchor | Index unverified NCT dump alone |

Quarantine rows with no crispro/CD/vulnerability/dilution/moat until re-extracted.

Re-build `aacr_embeddings` with `source_type` + filter metadata (Supabase re-index; auth declined this run so not executed here).

---

## Fix 3 — Flywheel / ML data quality

| Broken | Fix |
|---|---|
| All SFT `quality_score = 0.85` | Compute real gates: evidence quote in transcript, non-empty intel, valid talk_id, parse success → score ∈ [0,1] |
| All 450 rejected prefs = `fast_path_no_cd_analysis` stubs | Regenerate rejects with real failure modes: hallucinated opp, missing quote, wrong talk_id, empty arrays on rich talks |
| Extractor/B split | Train next SFT generation on **repaired** joined pairs |

Model build order stays: **reranker → extractor LoRA/DPO → fit ranker**; still do not train a custom embedder on this scale.

---

## Fix 4 — Downstream consumers

After remap + re-embed:

1. `match_embeddings` RPC — filter by `source_type`, lower threshold for short clinical facts
2. `aacr-semantic-search` / `crispro-scorer` / `cd-hit-extractor` — join on repaired `talk_id`
3. CRM push — only rows with `joined=yes` + priority high/medium

---

## Execution order

1. **Done in this PR:** root-cause analysis, `repair_talk_id_joins.py`, extractor_v6 guard, join map
2. Run `--write` and commit repaired Schema B + remapped masters
3. Triage `joined=no` sessions (re-extract ~50–80 talks, not full corpus)
4. Recompute flywheel quality scores + real DPO rejects
5. Re-embed claim units in Supabase + hybrid RPC
6. Gold-set eval (Recall@10 / entity hit-rate) before/after

---

## Success criteria

- [ ] Schema B `::unknown::` rate &lt; 5%
- [ ] A↔B join coverage ≥ 95% of valid B talks
- [ ] Zero orphan fragments in Schema B arrays
- [ ] Every production embedding has resolvable `talk_id`
- [ ] Flywheel quality scores non-constant
- [ ] Search gold-set entity hit-rate improves vs pre-repair baseline
