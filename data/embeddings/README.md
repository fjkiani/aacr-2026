# AACR embedding units (offline)

Claim-level units for offline index prep. **No embeddings computed here.** Supabase load is **out of scope / declined** — JSONL is the deliverable.

Includes **joined**, **unmatched**, and **provisional** (B-only) units with `metadata.join_status` + quality flags. Use `--joined-only` for legacy gate.

## Files

| File | Unit type |
|---|---|
| `talk_cards.jsonl` | talk_card (Schema A + provisional from B) |
| `clinical_facts.jsonl` | clinical_fact |
| `crispro_opps.jsonl` | crispro_opp |
| `cd_hits.jsonl` | cd_hit |
| `vulnerabilities.jsonl` | vulnerability |
| `all_units.jsonl` | combined |
| `build_summary.json` | counts + skip reasons + join_status |

## Record schema

```json
{
  "id": "talk_card:<talk_id>:<hash>",
  "unit_type": "talk_card",
  "talk_id": "session::lastname::N",
  "text": "string to embed",
  "metadata": {
    "speaker": "...",
    "join_status": "joined|unmatched|provisional",
    "provisional": false,
    "has_evidence": true,
    "has_entity": true
  },
  "source": "schema_a_master.json"
}
```

## Gates

- Resolvable `talk_id` **or** unmatched/provisional B id (when allow_provisional)
- Residual joined `::unknown::` intel (CrisPRO/CD/vuln) kept with `unknown_speaker` + `indexable=false` — no invented Schema A science
- Entity anchor (speaker / target / tumor / metric / opportunity type)
- Evidence present (MOA/findings, clinical value, quote, or CD/vuln text)

## Build counts (this run)

- talk_card: **929** (was 929)
- clinical_fact: **1480** (was 1480)
- crispro_opp: **1763** (was 1763)
- cd_hit: **464** (was 464)
- vulnerability: **675** (was 675)
- **total: 5311** (was 5311)

Join status: `{'joined': 5064, 'unmatched': 206, 'provisional': 41}`

Rebuild: `python3 scripts/build_embedding_units.py`
