#!/usr/bin/env python3
"""
Build offline claim-level embedding units from repaired Schema A/B masters.

Emits JSONL under data/embeddings/ ready for later Supabase load.
Does NOT call embedding APIs or Supabase.

Unit types:
  - talk_card
  - clinical_fact
  - crispro_opp
  - cd_hit
  - vulnerability

Quality gates (all units):
  - resolvable talk_id (joined=yes OR present in Schema A, not ::unknown:: unless
    talk_card from Schema A itself)
  - entity anchor (speaker / target / tumor / metric / opportunity type)
  - evidence present (MOA/findings, clinical value, transcript quote, or CD text)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "master"
OUT_DIR = ROOT / "data" / "embeddings"


def nonempty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip()) and v.strip().lower() not in {"unknown", "n/a", "none", ""}
    if isinstance(v, list):
        return any(nonempty(x) for x in v)
    if isinstance(v, dict):
        return any(nonempty(x) for x in v.values())
    return True


def has_quote(text: str | None) -> bool:
    if not text:
        return False
    return "speaker said" in text.lower() or bool(re.search(r'"[^"]{12,}"', text))


def load_joined_ids() -> set[str]:
    path = MASTER / "talk_id_join_map.csv"
    good: set[str] = set()
    if not path.exists():
        return good
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("joined") == "yes" and row.get("new_talk_id"):
                good.add(row["new_talk_id"])
    return good


def talk_id_ok(
    talk_id: str,
    joined: set[str],
    *,
    allow_schema_a_unknown: bool = False,
    require_joined_or_native: bool = True,
) -> bool:
    if not talk_id or "::" not in talk_id:
        return False
    if "::unknown::" in talk_id and not allow_schema_a_unknown:
        # Even if joined to an A unknown speaker, intel units stay quarantined
        return False
    if talk_id in joined:
        return True
    if "::unknown::" in talk_id:
        return allow_schema_a_unknown
    # Schema A native IDs (even if never appeared on B join map)
    return require_joined_or_native


def unit(
    *,
    unit_type: str,
    talk_id: str,
    text: str,
    metadata: dict,
    source: str,
) -> dict:
    uid = f"{unit_type}:{talk_id}:{abs(hash((unit_type, talk_id, text[:120]))) % (10**12)}"
    return {
        "id": uid,
        "unit_type": unit_type,
        "talk_id": talk_id,
        "text": text.strip(),
        "metadata": metadata,
        "source": source,
    }


def build_talk_cards(joined: set[str]) -> tuple[list[dict], Counter]:
    data = json.load(open(MASTER / "schema_a_master.json"))
    out = []
    skip = Counter()
    for rec in data:
        talk_id = rec.get("talk_id") or ""
        # Schema A is the identity source of truth — allow unknown speaker ids
        if not talk_id_ok(talk_id, joined, allow_schema_a_unknown=True):
            skip["bad_talk_id"] += 1
            continue
        speaker = (rec.get("speaker") or {}).get("name") or ""
        moa = rec.get("MOA_summary") or ""
        findings = rec.get("key_findings") or []
        if isinstance(findings, list):
            findings_txt = "; ".join(str(x) for x in findings[:5] if x)
        else:
            findings_txt = str(findings)
        targets = rec.get("targets") or []
        if isinstance(targets, list):
            # targets may be dicts or strings
            tnames = []
            for t in targets:
                if isinstance(t, dict):
                    tnames.append(t.get("name") or t.get("target") or "")
                else:
                    tnames.append(str(t))
            targets_txt = ", ".join(x for x in tnames if x)
        else:
            targets_txt = str(targets)
        tumors = rec.get("tumor_types") or []
        tumors_txt = ", ".join(tumors) if isinstance(tumors, list) else str(tumors)

        if not (nonempty(moa) or nonempty(findings_txt)):
            skip["no_evidence"] += 1
            continue
        # Quarantine talk cards that are only an unknown speaker with no targets
        if speaker.lower() == "unknown" and not nonempty(targets_txt):
            skip["low_signal_unknown"] += 1
            continue
        if not (
            nonempty(speaker)
            or nonempty(targets_txt)
            or nonempty(tumors_txt)
            or nonempty(rec.get("talk_title"))
        ):
            skip["no_entity"] += 1
            continue

        text = " | ".join(
            x
            for x in [
                rec.get("talk_title") or "",
                f"Speaker: {speaker}" if nonempty(speaker) else "",
                f"Tumors: {tumors_txt}" if tumors_txt else "",
                f"Targets: {targets_txt}" if targets_txt else "",
                f"MOA: {moa}" if moa else "",
                f"Findings: {findings_txt}" if findings_txt else "",
            ]
            if x
        )
        out.append(
            unit(
                unit_type="talk_card",
                talk_id=talk_id,
                text=text,
                metadata={
                    "speaker": speaker,
                    "session_title": rec.get("session_title"),
                    "talk_title": rec.get("talk_title"),
                    "clinical_stage": rec.get("clinical_stage"),
                    "tumor_types": tumors,
                    "topic_categories": rec.get("topic_categories"),
                    "novelty_flag": rec.get("novelty_flag"),
                },
                source="schema_a_master.json",
            )
        )
    return out, skip


def build_clinical(joined: set[str]) -> tuple[list[dict], Counter]:
    path = MASTER / "clinical_data_all.csv"
    out = []
    skip = Counter()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            talk_id = row.get("talk_id") or ""
            if not talk_id_ok(talk_id, joined, allow_schema_a_unknown=True):
                skip["bad_talk_id"] += 1
                continue
            metric = (row.get("metric") or "").strip()
            value = (row.get("value") or "").strip()
            if not metric or not value:
                skip["no_evidence"] += 1
                continue
            pop = row.get("population") or ""
            tumor = row.get("tumor_types") or ""
            stage = row.get("clinical_stage") or ""
            speaker = row.get("speaker_name") or ""
            if speaker.lower() == "unknown" and not nonempty(tumor):
                skip["low_signal_unknown"] += 1
                continue
            if not (nonempty(speaker) or nonempty(tumor) or nonempty(metric)):
                skip["no_entity"] += 1
                continue
            parts = [f"{metric} {value}"]
            if pop:
                parts.append(f"in {pop}")
            if tumor:
                parts.append(f"({tumor}")
                if stage:
                    parts[-1] += f", {stage}"
                parts[-1] += ")"
            elif stage:
                parts.append(f"({stage})")
            if speaker:
                parts.append(f"— {speaker}")
            text = " ".join(parts)
            out.append(
                unit(
                    unit_type="clinical_fact",
                    talk_id=talk_id,
                    text=text,
                    metadata={
                        "metric": metric,
                        "value": value,
                        "population": pop,
                        "tumor_types": tumor,
                        "clinical_stage": stage,
                        "maturity": row.get("maturity"),
                        "speaker": speaker,
                        "n": row.get("n"),
                        "comparator": row.get("comparator"),
                    },
                    source="clinical_data_all.csv",
                )
            )
    return out, skip


def build_crispro(joined: set[str]) -> tuple[list[dict], Counter]:
    path = MASTER / "crispro_opportunities_all.csv"
    out = []
    skip = Counter()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            talk_id = row.get("talk_id") or ""
            # Prefer joined / non-unknown for intel units
            if not talk_id_ok(talk_id, joined, allow_schema_a_unknown=False):
                skip["bad_talk_id"] += 1
                continue
            desc = (row.get("description") or "").strip()
            evidence = (row.get("transcript_evidence") or "").strip()
            angle = (row.get("crispro_angle") or "").strip()
            if not desc:
                skip["no_evidence"] += 1
                continue
            if not evidence:
                skip["no_evidence"] += 1
                continue
            speaker = row.get("speaker_name") or ""
            otype = row.get("opportunity_type") or ""
            if speaker.lower().startswith("dr. unknown") or speaker.lower() == "unknown":
                skip["low_signal_unknown"] += 1
                continue
            if not (nonempty(speaker) or nonempty(otype)):
                skip["no_entity"] += 1
                continue
            text = " | ".join(x for x in [desc, angle, evidence] if x)
            out.append(
                unit(
                    unit_type="crispro_opp",
                    talk_id=talk_id,
                    text=text,
                    metadata={
                        "opportunity_type": otype,
                        "priority": row.get("priority"),
                        "speaker": speaker,
                        "institution": row.get("institution"),
                        "session_title": row.get("session_title"),
                        "has_transcript_evidence": has_quote(evidence) or bool(evidence),
                    },
                    source="crispro_opportunities_all.csv",
                )
            )
    return out, skip


def build_cd_and_vuln(joined: set[str]) -> tuple[list[dict], list[dict], Counter, Counter]:
    data = json.load(open(MASTER / "schema_b_master.json"))
    cd_out, vuln_out = [], []
    skip_cd, skip_v = Counter(), Counter()
    for rec in data:
        talk_id = rec.get("talk_id") or ""
        md = rec.get("talk_metadata") or {}
        speaker = md.get("speaker_name") or ""
        ok = talk_id_ok(talk_id, joined, allow_schema_a_unknown=False)

        for cd in rec.get("cognitive_dissonance") or []:
            if not ok:
                skip_cd["bad_talk_id"] += 1
                continue
            text = cd if isinstance(cd, str) else json.dumps(cd, ensure_ascii=False)
            if not nonempty(text) or len(text) < 40:
                skip_cd["no_evidence"] += 1
                continue
            if speaker.lower().startswith("dr. unknown") or speaker.lower() == "unknown":
                skip_cd["low_signal_unknown"] += 1
                continue
            if not (nonempty(speaker) or nonempty(md.get("talk_title"))):
                skip_cd["no_entity"] += 1
                continue
            cd_out.append(
                unit(
                    unit_type="cd_hit",
                    talk_id=talk_id,
                    text=text,
                    metadata={
                        "speaker": speaker,
                        "session_title": md.get("session_title"),
                        "talk_title": md.get("talk_title"),
                        "presentation_type": md.get("presentation_type"),
                    },
                    source="schema_b_master.json",
                )
            )

        for v in rec.get("vulnerability_identified") or []:
            if not isinstance(v, dict):
                continue
            if not ok:
                skip_v["bad_talk_id"] += 1
                continue
            bits = [
                v.get("failure_type") or "",
                v.get("failing_compound_or_target") or "",
                v.get("mechanistic_blindspot") or "",
                v.get("evidence_quote") or v.get("transcript_evidence") or "",
            ]
            text = " | ".join(x for x in bits if x)
            if len(text) < 40:
                skip_v["no_evidence"] += 1
                continue
            if speaker.lower().startswith("dr. unknown") or speaker.lower() == "unknown":
                skip_v["low_signal_unknown"] += 1
                continue
            if not (
                nonempty(speaker)
                or nonempty(v.get("failing_compound_or_target"))
                or nonempty(v.get("failure_type"))
            ):
                skip_v["no_entity"] += 1
                continue
            vuln_out.append(
                unit(
                    unit_type="vulnerability",
                    talk_id=talk_id,
                    text=text,
                    metadata={
                        "speaker": speaker,
                        "failure_type": v.get("failure_type"),
                        "failing_compound_or_target": v.get("failing_compound_or_target"),
                        "evidence_strength": v.get("evidence_strength"),
                        "talk_title": md.get("talk_title"),
                    },
                    source="schema_b_master.json",
                )
            )
    return cd_out, vuln_out, skip_cd, skip_v


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    joined = load_joined_ids()
    talk_cards, skip_tc = build_talk_cards(joined)
    clinical, skip_cl = build_clinical(joined)
    crispro, skip_cr = build_crispro(joined)
    cd_hits, vulns, skip_cd, skip_v = build_cd_and_vuln(joined)

    write_jsonl(out_dir / "talk_cards.jsonl", talk_cards)
    write_jsonl(out_dir / "clinical_facts.jsonl", clinical)
    write_jsonl(out_dir / "crispro_opps.jsonl", crispro)
    write_jsonl(out_dir / "cd_hits.jsonl", cd_hits)
    write_jsonl(out_dir / "vulnerabilities.jsonl", vulns)

    all_units = talk_cards + clinical + crispro + cd_hits + vulns
    write_jsonl(out_dir / "all_units.jsonl", all_units)

    counts = {
        "talk_card": len(talk_cards),
        "clinical_fact": len(clinical),
        "crispro_opp": len(crispro),
        "cd_hit": len(cd_hits),
        "vulnerability": len(vulns),
        "total": len(all_units),
    }
    summary = {
        "counts": counts,
        "skips": {
            "talk_card": dict(skip_tc),
            "clinical_fact": dict(skip_cl),
            "crispro_opp": dict(skip_cr),
            "cd_hit": dict(skip_cd),
            "vulnerability": dict(skip_v),
        },
        "joined_talk_ids": len(joined),
        "schema": {
            "id": "stable unit id",
            "unit_type": "talk_card|clinical_fact|crispro_opp|cd_hit|vulnerability",
            "talk_id": "canonical Schema A talk_id when joined",
            "text": "string to embed",
            "metadata": "filterable fields (speaker, tumors, priority, ...)",
            "source": "origin master file",
        },
    }
    with open(out_dir / "build_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    readme = out_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# AACR embedding units (offline)",
                "",
                "Claim-level units for later Supabase / vector load. **No embeddings computed here.**",
                "",
                "## Files",
                "",
                "| File | Unit type |",
                "|---|---|",
                "| `talk_cards.jsonl` | talk_card |",
                "| `clinical_facts.jsonl` | clinical_fact |",
                "| `crispro_opps.jsonl` | crispro_opp |",
                "| `cd_hits.jsonl` | cd_hit |",
                "| `vulnerabilities.jsonl` | vulnerability |",
                "| `all_units.jsonl` | combined |",
                "| `build_summary.json` | counts + skip reasons |",
                "",
                "## Record schema",
                "",
                "```json",
                "{",
                '  "id": "talk_card:<talk_id>:<hash>",',
                '  "unit_type": "talk_card",',
                '  "talk_id": "session::lastname::N",',
                '  "text": "string to embed",',
                '  "metadata": { "speaker": "...", "tumor_types": [] },',
                '  "source": "schema_a_master.json"',
                "}",
                "```",
                "",
                "## Gates",
                "",
                "- Resolvable `talk_id` (joined B→A for intel units; Schema A IDs for talk/clinical)",
                "- Entity anchor (speaker / target / tumor / metric / opportunity type)",
                "- Evidence present (MOA/findings, clinical value, quote, or CD/vuln text)",
                "",
                f"## Build counts (this run)",
                "",
                f"- talk_card: **{counts['talk_card']}**",
                f"- clinical_fact: **{counts['clinical_fact']}**",
                f"- crispro_opp: **{counts['crispro_opp']}**",
                f"- cd_hit: **{counts['cd_hit']}**",
                f"- vulnerability: **{counts['vulnerability']}**",
                f"- **total: {counts['total']}**",
                "",
                "Rebuild: `python3 scripts/build_embedding_units.py`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print("Embedding units built:")
    for k, v in counts.items():
        print(f"  {k:16} {v}")
    print(f"  → {out_dir}")


if __name__ == "__main__":
    main()
