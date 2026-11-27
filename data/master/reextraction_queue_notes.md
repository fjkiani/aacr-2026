# Re-extraction queue notes

Offline triage of unmatched Schema B talks after improved join cascade.
OpenRouter / LLM re-extraction was **not** run (keys unavailable / not required for this pass).

## Summary

- Unmatched B talks: **71** across **47** sessions
- Reason categories: `{'count_mismatch': 49, 'no_schema_a': 16, 'low_signal': 4, 'asr_name': 2}`
- Sessions blocked without Schema A: **5**

## Blocked sessions (need Schema A extraction first)

- `aacr-margaret-foti-award-for-leadership-and-extraordinary-achievements-in-cancer` — 1 B talks, speakers: Dr. Anthony Ribas
- `leveraging-nci-supported-cancer-epidemiology-cohorts-to-advance-cancer-preventio` — 5 B talks, speakers: Dr. Iona Cheng; Dr. Jim Doohan; Dr. Elena Martinez; Dr. Shelley Tworoger; Wei Zheng
- `nci-opportunities-in-technology-development-for-cancer-research` — 3 B talks, speakers: Kelly Crotty; Andrew Eady; Mary Goldman
- `nci-opportunities-to-support-early-career-cancer-researchers-and-research-specia` — 4 B talks, speakers: Chanelle Borden; Mark D'Amico; Susan Lim; Kelly Crotty
- `researcher-town-hall-navigating-policy-challenges-and-securing-funding` — 3 B talks, speakers: Roy Herbst; John Wherry; Patty Spears

## Actions for remaining sessions

1. Prefer one LLM call that emits **aligned A+B** for the session so IDs are assigned together.
2. For `asr_name` with leftover A speakers, a human pass matching names is often enough (no full re-extract).
3. Pure `count_mismatch` with zero leftover A means B extracted chairs/panelists A never modeled — drop or quarantine those B rows for embedding.

Artifacts: `data/master/unmatched_talk_triage.csv`, `data/master/reextraction_queue.csv`.
