# AACR embedding units (offline)

Claim-level units for later Supabase / vector load. **No embeddings computed here.**

## Files

| File | Unit type |
|---|---|
| `talk_cards.jsonl` | talk_card |
| `clinical_facts.jsonl` | clinical_fact |
| `crispro_opps.jsonl` | crispro_opp |
| `cd_hits.jsonl` | cd_hit |
| `vulnerabilities.jsonl` | vulnerability |
| `all_units.jsonl` | combined |
| `build_summary.json` | counts + skip reasons |

## Record schema

```json
{
  "id": "talk_card:<talk_id>:<hash>",
  "unit_type": "talk_card",
  "talk_id": "session::lastname::N",
  "text": "string to embed",
  "metadata": { "speaker": "...", "tumor_types": [] },
  "source": "schema_a_master.json"
}
```

## Gates

- Resolvable `talk_id` (joined B→A for intel units; Schema A IDs for talk/clinical)
- Entity anchor (speaker / target / tumor / metric / opportunity type)
- Evidence present (MOA/findings, clinical value, quote, or CD/vuln text)

## Build counts (this run)

- talk_card: **858**
- clinical_fact: **1480**
- crispro_opp: **1752**
- cd_hit: **461**
- vulnerability: **671**
- **total: 5222**

Rebuild: `python3 scripts/build_embedding_units.py`
