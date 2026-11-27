# AACR 2026 — Vectorization & ML Audit

**Scope:** Local corpus in `fjkiani/aacr-2026` (transcripts → Schema A/B → master aggregates → flywheel).  
**Supabase:** Live `aacr_embeddings` / `match_embeddings` not inspected this run (auth declined). Counts below from README + local files.

---

## Verdict

**Do not embed raw transcripts.** Embed **claim-level structured units** after fixing identity joins and applying quality gates. Train **task models** (extractor + reranker + opportunity ranker) on the flywheel — not a custom embedding model from 862 rows.

---

## Current state

| Layer | What exists | Scale |
|---|---|---|
| Raw captions | Auto-generated VTT → cleaned TXT | 272 sessions, ~76k chars avg |
| Schema A | Scientific talk cards | 862 speakers |
| Schema B | Competitive intel | 926 rows |
| Clinical facts | Flattened metrics | 1,480 rows |
| CrisPRO opps | Opportunity rows | ~1,763 (900 high / 852 medium / 11 low) |
| Embeddings (reported) | Supabase `aacr_embeddings` IVFFlat | 3,024 rows, cosine thresh 0.65 |
| Flywheel | SFT + preference pairs | 862 SFT + 450 prefs |
| Downstream | `aacr-semantic-search` → CRM pipeline | openclaw-saas skills |

Likely embedding mix (inferred, not verified live):  
`sessions (296) + speakers (862) + competitive_intel (926) + clinical subset (~940) ≈ 3,024`.

---

## What makes vectors junk here

### 1. Wrong unit of retrieval
Raw session text (~76k chars) mixes chairs, Q&A, ASR noise, and multiple talks. Cosine neighbors become “same room vibe,” not “same claim.”

### 2. Broken identity join (critical) — repaired in this PR
Schema A ↔ Schema B `talk_id` alignment was nearly broken pre-repair:

| Check | Before | After cascade v2 |
|---|---|---|
| Exact `talk_id` intersection | **22 / 862+926** | Canonical B IDs rewritten to A when joined |
| Schema B `::unknown::` talk_ids | **891 / 926** | **5 / 881** |
| Valid B joined to A | — | **810 / 881 (91.9%)** · **810 / 865 joinable (93.6%)** |

See `reports/fix_plan_identity_and_vectors.md` + `data/master/talk_id_join_map.csv`. Residual unmatched triage: `data/master/unmatched_talk_triage.csv`.

### 3. Caption ASR risk
All 272 transcripts are **English auto-generated**. Drug names, gene symbols, NCT IDs, and dose numbers are the highest-value tokens and the most error-prone.

### 4. Fake quality signal — rescored offline
Original seed had all 862 SFT rows at `quality_score = 0.8500` and stub rejects. Rescored copy: `data/flywheel/aacr_flywheel_seed_scored.json` (8 unique scores, mean 0.934) + 450 synthetic failure-mode rejects. See `reports/flywheel_quality_summary.md`.

### 5. Low-signal Schema B rows
73 Schema B records have empty vulnerability / dilution / moat / CD / CrisPRO arrays. Embedding those pollutes the index with near-empty cards.

### 6. Abstract enrichment noise (separate corpus)
Gap report: 7,485 abstracts, only 47.6% axis-enriched; 27.3% keyword fallback. Keyword hits are directional, not embedding-grade claims.

---

## Non-junk vectorization approach

### Principle
**Retrieve claims, not sessions.** Every vector must answer: *who said what about which target/tumor/trial, with what evidence.*

### Step 0 — Fix identity before any re-embed
1. Rebuild Schema B `talk_id` to match Schema A (`session_slug::last_name::index`).
2. Where speaker ASR is bad, join by **order within session** (588 talks already count-aligned) + fuzzy name match on affiliation.
3. Persist a canonical `entity_id` on sessions, talks, clinical facts, opps, CD hits.
4. Drop or quarantine low-signal Schema B rows until re-extracted.

### Step 1 — Embedding units (tiered)

| Unit | Text to embed | Metadata filters | Why |
|---|---|---|---|
| **Talk card** | `talk_title` + `MOA_summary` + top `key_findings` + targets/tumors | speaker, stage, topics, tumor | Primary semantic search |
| **Clinical fact** | `{metric} {value} in {population} ({tumor}, {stage})` + speaker | metric, maturity, talk_id | Exact readout retrieval |
| **CrisPRO opportunity** | `description` + `crispro_angle` + `transcript_evidence` | priority, opportunity_type | BD / white-space search |
| **CD / vulnerability** | quote + dissonance/failure fields | failure_type, evidence_strength | Competitive intel search |
| **Session summary** (optional) | title + category + joined talk MOAs (short) | place, category | Navigation only |

**Do not embed:** raw VTT, full TXT, empty arrays, unverified NCT dump alone, keyword-only abstract stubs without LLM claim text.

### Step 2 — Quality gates (reject before embed)
Embed only if unit passes:

- Non-empty core text ≥ N chars (talk card: MOA present; opp: evidence quote present).
- At least one entity anchor: gene/drug/tumor/NCT/speaker.
- `talk_id` resolvable to Schema A.
- Optional: ASR confidence / glossary repair for gene/drug tokens against a controlled vocab (KRAS, STC-1010, etc.).
- Dedup near-identical strings (hash + cosine self-sim).

### Step 3 — Hybrid retrieval (required)
Dense embeddings alone will fail on rare tokens (`PKMYT1`, `MBD4_LOF`, NCT IDs).

```
query
  → sparse BM25 / trigram on gene, drug, NCT, speaker
  → dense match_embeddings (talk + opp + clinical units)
  → metadata prefilter (tumor, stage, priority, axis)
  → cross-encoder rerank (top 50 → top 10)
```

Keep threshold flexible by unit type; 0.65 global is too blunt for short clinical facts vs long MOA cards.

### Step 4 — Index layout (Supabase)
Suggested rows (replace flat 3,024 dump):

- `source_type`: `talk_card | clinical_fact | crispro_opp | cd_hit | vulnerability`
- `entity_id`, `talk_id`, `session_slug`
- `text`, `embedding`, `token_count`
- `filters` jsonb: tumors, targets, stage, priority, opportunity_type
- `quality_flags` jsonb: asr_repaired, evidence_present, join_method

Separate IVFFlat / HNSW indexes per `source_type` or filter in RPC.

### Step 5 — Eval before declaring “not junk”
Build a 50–100 query gold set from real BD questions, e.g.:

- “MSS CRC vaccine competitors”
- “PKMYT1 Phase I readouts”
- “ADC resistance admissions”
- speaker / drug lookup

Metrics: Recall@10, nDCG@10, entity hit-rate (correct gene/drug in top-k), join integrity (% results with valid talk_id).

---

## How to build the ML model(s)

You already have the start of a **training flywheel**, not an embedding corpus. Use it that way.

### Model A — Competitive-intel extractor (primary)
**Goal:** Schema B (and tighter Schema A) extraction that cites transcript evidence.

| Ingredient | Use |
|---|---|
| 862 SFT rows | Supervised fine-tune / LoRA on `competitive_intel_extraction` |
| 450 pref pairs | DPO/ORPO — but **regenerate rejected** with real failure modes (hallucinated opp, missing quote, wrong talk_id), not empty stubs |
| Transcript snippets | Always include grounded excerpt in prompt, not only schema JSON |

**Eval:** exact-field F1 on held-out sessions; quote entailment (evidence span must appear in transcript); talk_id accuracy; hallucination rate on empty-intel sessions.

### Model B — Retrieval reranker (highest ROI for “not junk search”)
Train a cross-encoder: `(query, candidate_unit) → relevance`.

Labels from:
- Expert clicks / CRM pushes in openclaw pipeline
- Synthetic pairs from Schema fields (“KRAS G12D” ↔ talk cards containing KRAS G12D)
- Hard negatives: same tumor, wrong target

This improves search faster than re-embedding everything.

### Model C — Opportunity / fit ranker
Supervised ranker on CrisPRO rows:

- Features: opportunity_type, priority, tumor overlap with Brenus/CrisPRO axes, maturity, CD present, target axis tags
- Labels: existing priority + human BD triage (fit scores already appear in gap briefs)
- Output: `crispro_fit ∈ [0,1]` for CRM prioritization

Start with gradient boosting on structured features; only deep-learn if text features dominate.

### Model D — Do **not** train a custom embedding model yet
862–3k rows is far below what you need to beat `text-embedding-3-large` / voyage / biomed embeddings. Prefer:

1. Off-the-shelf embedder on cleaned claim units
2. Domain glossary prepend (`[GENE] KRAS [DRUG] sotorasib …`)
3. Optional: fine-tune embedder later with contrastive pairs from Model B labels

### Recommended build order
1. **Join repair + quality gates** (unblocks everything)
2. **Re-embed claim units + hybrid RPC**
3. **Reranker** with synthetic + sparse human labels
4. **Extractor LoRA + real DPO prefs**
5. **Opportunity ranker** wired to CRM push

---

## Concrete anti-junk checklist

- [x] Offline claim units built (`data/embeddings/`, 5,222 gated rows) — no raw transcript units
- [x] Intel units require resolvable non-`::unknown::` `talk_id`
- [x] Evidence/value required for clinical / CrisPRO / CD / vuln units
- [ ] Gene/drug sparse index alongside dense (needs Supabase load)
- [x] Constant `quality_score=0.85` replaced with real gates
- [x] Preference rejects regenerated with factual errors
- [ ] Gold query set scored before/after re-embed
- [ ] NCT IDs stay unverified until linked — never sole embed text
- [ ] Production Supabase re-index (auth declined this run)

---

## Bottom line

Vectorize **structured, evidence-bearing talk/clinical/opportunity atoms** after repairing Schema A/B identity. Build ML as an **extractor + reranker + fit-ranker flywheel**, using the existing 862/450 seed as bootstrapping data — not as a reason to train embeddings from scratch.
