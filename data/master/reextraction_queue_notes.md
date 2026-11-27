# Re-extraction queue notes

Offline triage of unmatched Schema B talks after improved join cascade.
OpenRouter / LLM re-extraction was **not** run (keys unavailable). Offline stubs + notes only.

## Summary

- Unmatched B talks: **71** across **47** sessions
- Reason categories: `{'count_mismatch': 49, 'no_schema_a': 16, 'low_signal': 4, 'asr_name': 2}`
- Sessions blocked without Schema A: **5**

## Priority order (top 15)

| Rank | Session | Reason | Unmatched B | Action |
|---|---|---|---|---|
| 1 | `leveraging-nci-supported-cancer-epidemiology-coh` | no_schema_a | 5 | `extract_schema_a_missing` |
| 2 | `nci-opportunities-to-support-early-career-cancer` | no_schema_a | 4 | `extract_schema_a_missing` |
| 3 | `nci-opportunities-in-technology-development-for-` | no_schema_a | 3 | `extract_schema_a_missing` |
| 4 | `researcher-town-hall-navigating-policy-challenge` | no_schema_a | 3 | `extract_schema_a_missing` |
| 5 | `aacr-margaret-foti-award-for-leadership-and-extr` | no_schema_a | 1 | `extract_schema_a_missing` |
| 6 | `cracking-adaptive-resistance-ai-enabled-screen-g` | asr_name | 2 | `reextract_or_manual_asr_resolve` |
| 7 | `combating-t-cell-checkpoints` | count_mismatch | 4 | `reextract_aligned_ab` |
| 8 | `cancer-prevention-and-screening-exploring-policy` | count_mismatch | 2 | `reextract_aligned_ab` |
| 9 | `contextual-challenges-in-interpreting-performanc` | count_mismatch | 2 | `reextract_aligned_ab` |
| 10 | `improving-cancer-outcomes-by-shaping-the-tumor-m` | count_mismatch | 2 | `reextract_aligned_ab` |
| 11 | `ncinih-consortia-initiative-metabolic-dysregulat` | count_mismatch | 2 | `reextract_aligned_ab` |
| 12 | `novel-molecular-mechanisms-driving-cancer-metast` | count_mismatch | 2 | `reextract_aligned_ab` |
| 13 | `patient-advocate-poster-symposium-advancing-canc` | count_mismatch | 2 | `reextract_aligned_ab` |
| 14 | `the-aacr-project-genie-data-model-a-foundation-f` | count_mismatch | 2 | `reextract_aligned_ab` |
| 15 | `aacr-annual-meeting-2026-highlights` | count_mismatch | 1 | `reextract_aligned_ab` |

## Blocked sessions (need Schema A extraction first)

- `leveraging-nci-supported-cancer-epidemiology-cohorts-to-advance-cancer-preventio` — 5 B talks, speakers: Dr. Iona Cheng; Dr. Jim Doohan; Dr. Elena Martinez; Dr. Shelley Tworoger; Wei Zheng
- `nci-opportunities-to-support-early-career-cancer-researchers-and-research-specia` — 4 B talks, speakers: Chanelle Borden; Mark D'Amico; Susan Lim; Kelly Crotty
- `nci-opportunities-in-technology-development-for-cancer-research` — 3 B talks, speakers: Kelly Crotty; Andrew Eady; Mary Goldman
- `researcher-town-hall-navigating-policy-challenges-and-securing-funding` — 3 B talks, speakers: Roy Herbst; John Wherry; Patty Spears
- `aacr-margaret-foti-award-for-leadership-and-extraordinary-achievements-in-cancer` — 1 B talks, speakers: Dr. Anthony Ribas

## Actions for remaining sessions

1. Prefer one LLM call that emits **aligned A+B** for the session so IDs are assigned together.
2. For `asr_name` with leftover A speakers, a human pass matching names is often enough (no full re-extract).
3. Pure `count_mismatch` with zero leftover A means B extracted chairs/panelists A never modeled — keep as **provisional** embedding units (`join_status=unmatched`) rather than dropping.
4. B-only sessions: provisional talk cards are synthesized from Schema B metadata for index prep.

Offline stubs: `data/master/reextraction_stubs`

Artifacts: `data/master/unmatched_talk_triage.csv`, `data/master/reextraction_queue.csv`.
