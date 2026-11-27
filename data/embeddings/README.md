# AACR embedding units (offline)

Claim-level units for later Supabase / vector load. **No embeddings computed here.**

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
- Entity anchor (speaker / target / tumor / metric / opportunity type)
- Evidence present (MOA/findings, clinical value, quote, or CD/vuln text)

## Build counts (this run)

- talk_card: **929** (was 858)
- clinical_fact: **1480** (was 1480)
- crispro_opp: **1752** (was 1752)
- cd_hit: **461** (was 461)
- vulnerability: **671** (was 671)
- **total: 5293** (was 5222)

Join status: `{'joined': 5046, 'unmatched': 206, 'provisional': 41}`

Rebuild: `python3 scripts/build_embedding_units.py`
