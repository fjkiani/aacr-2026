"""Argparse entrypoints — keep scripts/*.py as thin wrappers."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import embedding_units as eu
from . import flywheel_quality as fq
from . import identity
from . import reextract
from . import triage as triage_mod
from .paths import DIR_A, DIR_B, EMBEDDINGS, FLYWHEEL, MASTER, REPORTS, ROOT
from .schema_b_clean import (
    a_speaker_name,
    b_speaker_name,
    b_talk_title,
    filter_valid_b,
    is_valid_b,
)


def _load_sessions() -> tuple[dict[str, list], dict[str, list]]:
    a_by, b_by = {}, {}
    for f in DIR_A.glob("*.json"):
        a_by[f.stem] = json.load(open(f))
    for f in DIR_B.glob("*.json"):
        b_by[f.stem] = json.load(open(f))
    return a_by, b_by


def _remap_csv(path: Path, id_map: dict[str, str]) -> int:
    if not path.exists():
        return 0
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    if "talk_id" not in fieldnames:
        return 0
    n = 0
    for row in rows:
        old = row.get("talk_id") or ""
        if old in id_map and id_map[old] != old:
            row["talk_id"] = id_map[old]
            n += 1
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return n


def repair_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Repair Schema B talk_id joins to Schema A")
    ap.add_argument("--write", action="store_true", help="Write repaired files")
    args = ap.parse_args(argv)

    a_by, b_by = _load_sessions()
    join_rows = []
    id_map: dict[str, str] = {}
    methods = defaultdict(int)
    orphans_dropped = 0
    repaired_sessions = 0

    for slug in sorted(set(a_by) | set(b_by)):
        A = a_by.get(slug, [])
        raw_B = b_by.get(slug, [])
        valid_B, dropped = filter_valid_b(raw_B)
        orphans_dropped += dropped
        if not raw_B:
            continue

        pairs = (
            identity.cascade_join(A, valid_B)
            if A
            else [(None, "no_schema_a")] * len(valid_B)
        )
        new_records = []
        for bi, (ai, method) in enumerate(pairs):
            rec = valid_B[bi]
            old_id = rec.get("talk_id") or ""
            canonical = A[ai]["talk_id"] if ai is not None else None
            new_id = identity.rewrite_b_talk_id(
                slug, rec, (ai + 1) if ai is not None else (bi + 1), canonical
            )
            methods[method] += 1
            join_rows.append(
                {
                    "session_slug": slug,
                    "method": method,
                    "old_talk_id": old_id,
                    "new_talk_id": new_id,
                    "a_speaker": (a_speaker_name(A[ai]) if ai is not None else ""),
                    "b_speaker": b_speaker_name(rec),
                    "a_talk_title": (A[ai].get("talk_title") if ai is not None else ""),
                    "b_talk_title": b_talk_title(rec),
                    "joined": "yes" if ai is not None else "no",
                }
            )
            if old_id and new_id != old_id:
                id_map[old_id] = new_id
            rec = dict(rec)
            rec["talk_id"] = new_id
            new_records.append(rec)

        if args.write:
            with open(DIR_B / f"{slug}.json", "w") as f:
                json.dump(new_records, f, indent=2)
                f.write("\n")
            repaired_sessions += 1

    joined = sum(1 for r in join_rows if r["joined"] == "yes")
    joinable = sum(1 for r in join_rows if r["method"] != "no_schema_a")
    print("Schema B repair summary")
    print(f"  valid B rows processed : {len(join_rows)}")
    print(f"  orphan fragments drop  : {orphans_dropped}")
    print(f"  joined to Schema A     : {joined} ({joined / max(len(join_rows), 1):.1%})")
    if joinable:
        print(f"  of joinable (has A)    : {joined}/{joinable} ({joined / joinable:.1%})")
    print(f"  unmatched B            : {len(join_rows) - joined}")
    print(f"  methods                : {dict(methods)}")
    print(f"  talk_id remaps         : {len(id_map)}")

    MASTER.mkdir(parents=True, exist_ok=True)
    map_path = MASTER / "talk_id_join_map.csv"
    fields = [
        "session_slug",
        "method",
        "old_talk_id",
        "new_talk_id",
        "a_speaker",
        "b_speaker",
        "a_talk_title",
        "b_talk_title",
        "joined",
    ]
    with open(map_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(join_rows)
    print(f"  wrote {map_path}")

    if args.write:
        master = []
        for f in sorted(DIR_B.glob("*.json")):
            master.extend(json.load(open(f)))
        with open(MASTER / "schema_b_master.json", "w") as f:
            json.dump(master, f, indent=2)
            f.write("\n")
        print(f"  wrote schema_b_master.json ({len(master)} rows)")

        csv_rows = []
        for r in master:
            md = r.get("talk_metadata") or {}
            vulns = r.get("vulnerability_identified") or []
            opps = r.get("crispro_opportunity") or []
            cd = r.get("cognitive_dissonance") or []
            csv_rows.append(
                {
                    "talk_id": r.get("talk_id", ""),
                    "speaker_name": md.get("speaker_name", ""),
                    "institution": md.get("institution_or_pharma", ""),
                    "session_title": md.get("session_title", ""),
                    "talk_title": md.get("talk_title", ""),
                    "presentation_type": md.get("presentation_type", ""),
                    "rhetorical_signals": " | ".join(md.get("rhetorical_signals") or []),
                    "cognitive_dissonance": json.dumps(cd, ensure_ascii=False) if cd else "",
                    "n_vulnerabilities": len(vulns),
                    "vulnerability_type": ";".join(
                        v.get("failure_type", "") for v in vulns if isinstance(v, dict)
                    ),
                    "failing_target": ";".join(
                        v.get("failing_compound_or_target", "")
                        for v in vulns
                        if isinstance(v, dict)
                    ),
                    "mechanistic_blindspot": ";".join(
                        (v.get("mechanistic_blindspot") or "")
                        for v in vulns
                        if isinstance(v, dict)
                    ),
                    "evidence_strength": ";".join(
                        (v.get("evidence_strength") or "")
                        for v in vulns
                        if isinstance(v, dict)
                    ),
                    "n_trial_dilution_risks": len(r.get("trial_dilution_risk") or []),
                    "n_crispro_opportunities": len(opps),
                }
            )
        csv_path = MASTER / "schema_b_master.csv"
        old_fields = None
        if csv_path.exists():
            with open(csv_path, newline="") as f:
                old_fields = csv.DictReader(f).fieldnames
        fields_csv = list(old_fields or csv_rows[0].keys())
        for k in csv_rows[0].keys():
            if k not in fields_csv:
                fields_csv.append(k)
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields_csv, extrasaction="ignore")
            w.writeheader()
            w.writerows(csv_rows)
        print(f"  wrote schema_b_master.csv ({len(csv_rows)} rows)")

        for name in ["crispro_opportunities_all.csv", "cognitive_dissonance_all.csv"]:
            n = _remap_csv(MASTER / name, id_map)
            print(f"  remapped {name}: {n} talk_ids")
        print(f"  repaired schema_b sessions: {repaired_sessions}")
    else:
        print("  dry-run only (pass --write to mutate extraction files + masters)")


def triage_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Triage unmatched Schema B talks")
    ap.add_argument(
        "--stubs",
        type=int,
        default=10,
        help="Write top-N offline re-extraction stubs (0 to skip)",
    )
    args = ap.parse_args(argv)

    map_path = MASTER / "talk_id_join_map.csv"
    rows = list(csv.DictReader(open(map_path, newline="")))
    a_by, b_by = _load_sessions()
    triage_rows, qrows = triage_mod.build_triage(rows, a_by, b_by, is_valid_b)

    triage_path = MASTER / "unmatched_talk_triage.csv"
    fields = list(triage_rows[0].keys()) if triage_rows else []
    with open(triage_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(triage_rows)

    queue_path = MASTER / "reextraction_queue.csv"
    qfields = list(qrows[0].keys()) if qrows else []
    with open(queue_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=qfields)
        w.writeheader()
        w.writerows(qrows)

    stubs_rel = None
    api_attempted = False
    if args.stubs > 0:
        if reextract.has_llm_keys():
            summary = reextract.attempt_limited_reextract(qrows, limit=min(3, args.stubs))
            api_attempted = bool(summary.get("attempted"))
            # Still write stubs as fallback context
            stubs_dir = reextract.write_offline_stubs(qrows, top_n=args.stubs)
        else:
            stubs_dir = reextract.write_offline_stubs(qrows, top_n=args.stubs)
        stubs_rel = str(stubs_dir.relative_to(ROOT))

    notes = MASTER / "reextraction_queue_notes.md"
    notes.write_text(
        triage_mod.notes_markdown(
            triage_rows,
            qrows,
            triage_rel=str(triage_path.relative_to(ROOT)),
            queue_rel=str(queue_path.relative_to(ROOT)),
            stubs_rel=stubs_rel,
            api_attempted=api_attempted,
        ),
        encoding="utf-8",
    )

    cat_counts = Counter(t["reason_category"] for t in triage_rows)
    print(f"wrote {triage_path} ({len(triage_rows)} rows)")
    print(f"wrote {queue_path} ({len(qrows)} sessions)")
    print(f"wrote {notes}")
    print(f"categories: {dict(cat_counts)}")
    if stubs_rel:
        print(f"stubs: {stubs_rel} (top {args.stubs})")


def flywheel_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Recompute flywheel quality scores")
    ap.add_argument("--in", dest="infile", default=str(FLYWHEEL / "aacr_flywheel_seed.json"))
    ap.add_argument(
        "--out", dest="outfile", default=str(FLYWHEEL / "aacr_flywheel_seed_scored.json")
    )
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args(argv)

    src = json.load(open(args.infile))
    a_path = MASTER / "schema_a_master.json"
    a_ids = set()
    if a_path.exists():
        a_ids = {r.get("talk_id") for r in json.load(open(a_path)) if r.get("talk_id")}
    joined_ids = eu.load_joined_ids()

    out, stats = fq.rescore_flywheel(
        src, a_ids=a_ids, joined_ids=joined_ids, seed=args.seed
    )
    out_path = Path(args.outfile)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out["meta"]["quality_rescoring"]["source"] = Path(args.infile).name
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    scores = stats["scores"]
    mean = sum(scores) / max(len(scores), 1)
    unique = len(set(scores))
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / "flywheel_quality_summary.md"
    lines = [
        "# Flywheel quality rescoring summary",
        "",
        f"Source: `{Path(args.infile).relative_to(ROOT)}`  ",
        f"Output: `{out_path.relative_to(ROOT)}`",
        "",
        "## SFT quality_score",
        "",
        f"- Rows: **{len(scores)}**",
        f"- Unique scores (was 1×0.85): **{unique}**",
        f"- Mean: **{mean:.4f}**",
        f"- Min / max: **{min(scores):.4f}** / **{max(scores):.4f}**",
        "",
        "### Distribution",
        "",
        "| Score | Count |",
        "|---|---|",
    ]
    for bucket, n in sorted(stats["score_hist"].items(), key=lambda x: -float(x[0])):
        lines.append(f"| {bucket} | {n} |")
    lines += [
        "",
        "### Gate pass rates",
        "",
        "| Gate | Pass | Rate |",
        "|---|---|---|",
    ]
    for k in (
        "parse_complete",
        "moa_present",
        "moa_substantive",
        "findings_present",
        "findings_rich",
        "talk_id_resolvable",
        "entity_anchor",
        "speaker_known",
        "stage_specified",
        "evidence_quote",
    ):
        n = stats["gate_counts"][k]
        lines.append(f"| `{k}` | {n} | {n / max(len(scores), 1):.1%} |")
    lines += [
        "",
        "## Preference rejects",
        "",
        f"- Regenerated: **{stats['pref_count']}** (was all `fast_path_no_cd_analysis`)",
        "",
        "| Failure mode | Count |",
        "|---|---|",
    ]
    for mode, n in stats["reject_modes"].most_common():
        lines.append(f"| `{mode}` | {n} |")
    lines += [
        "",
        "Rejects are synthetic/offline transformations of the chosen response — no LLM API used.",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {out_path}")
    print(f"wrote {report}")
    print(
        f"SFT scores: unique={unique} mean={mean:.4f} "
        f"min={min(scores):.4f} max={max(scores):.4f}"
    )
    print(f"score_hist={dict(stats['score_hist'])}")
    print(f"reject_modes={dict(stats['reject_modes'])}")
    print(f"gate_pass={dict(stats['gate_counts'])}")


def embeddings_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build claim-level embedding units (joined + provisional)"
    )
    ap.add_argument("--out-dir", default=str(EMBEDDINGS))
    ap.add_argument(
        "--joined-only",
        action="store_true",
        help="Exclude unmatched/provisional units (legacy gate)",
    )
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    before = {}
    before_path = out_dir / "build_summary.json"
    if before_path.exists():
        try:
            before = json.load(open(before_path)).get("counts") or {}
        except json.JSONDecodeError:
            before = {}

    allow_prov = not args.joined_only
    bundles, summary = eu.build_all(allow_provisional=allow_prov)
    summary["before_counts"] = before

    eu.write_jsonl(out_dir / "talk_cards.jsonl", bundles["talk_card"])
    eu.write_jsonl(out_dir / "clinical_facts.jsonl", bundles["clinical_fact"])
    eu.write_jsonl(out_dir / "crispro_opps.jsonl", bundles["crispro_opp"])
    eu.write_jsonl(out_dir / "cd_hits.jsonl", bundles["cd_hit"])
    eu.write_jsonl(out_dir / "vulnerabilities.jsonl", bundles["vulnerability"])
    all_units = (
        bundles["talk_card"]
        + bundles["clinical_fact"]
        + bundles["crispro_opp"]
        + bundles["cd_hit"]
        + bundles["vulnerability"]
    )
    eu.write_jsonl(out_dir / "all_units.jsonl", all_units)

    with open(out_dir / "build_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    counts = summary["counts"]
    js_counts = summary.get("join_status_counts") or {}
    readme = out_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# AACR embedding units (offline)",
                "",
                "Claim-level units for later Supabase / vector load. **No embeddings computed here.**",
                "",
                "Includes **joined**, **unmatched**, and **provisional** (B-only) units with "
                "`metadata.join_status` + quality flags. Use `--joined-only` for legacy gate.",
                "",
                "## Files",
                "",
                "| File | Unit type |",
                "|---|---|",
                "| `talk_cards.jsonl` | talk_card (Schema A + provisional from B) |",
                "| `clinical_facts.jsonl` | clinical_fact |",
                "| `crispro_opps.jsonl` | crispro_opp |",
                "| `cd_hits.jsonl` | cd_hit |",
                "| `vulnerabilities.jsonl` | vulnerability |",
                "| `all_units.jsonl` | combined |",
                "| `build_summary.json` | counts + skip reasons + join_status |",
                "",
                "## Record schema",
                "",
                "```json",
                "{",
                '  "id": "talk_card:<talk_id>:<hash>",',
                '  "unit_type": "talk_card",',
                '  "talk_id": "session::lastname::N",',
                '  "text": "string to embed",',
                '  "metadata": {',
                '    "speaker": "...",',
                '    "join_status": "joined|unmatched|provisional",',
                '    "provisional": false,',
                '    "has_evidence": true,',
                '    "has_entity": true',
                "  },",
                '  "source": "schema_a_master.json"',
                "}",
                "```",
                "",
                "## Gates",
                "",
                "- Resolvable `talk_id` **or** unmatched/provisional B id (when allow_provisional)",
                "- Entity anchor (speaker / target / tumor / metric / opportunity type)",
                "- Evidence present (MOA/findings, clinical value, quote, or CD/vuln text)",
                "",
                "## Build counts (this run)",
                "",
                f"- talk_card: **{counts['talk_card']}**"
                + (f" (was {before.get('talk_card')})" if before else ""),
                f"- clinical_fact: **{counts['clinical_fact']}**"
                + (f" (was {before.get('clinical_fact')})" if before else ""),
                f"- crispro_opp: **{counts['crispro_opp']}**"
                + (f" (was {before.get('crispro_opp')})" if before else ""),
                f"- cd_hit: **{counts['cd_hit']}**"
                + (f" (was {before.get('cd_hit')})" if before else ""),
                f"- vulnerability: **{counts['vulnerability']}**"
                + (f" (was {before.get('vulnerability')})" if before else ""),
                f"- **total: {counts['total']}**"
                + (f" (was {before.get('total')})" if before else ""),
                "",
                f"Join status: `{js_counts}`",
                "",
                "Rebuild: `python3 scripts/build_embedding_units.py`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print("Embedding units built:")
    for k, v in counts.items():
        prev = before.get(k)
        delta = f" ({'+' if prev is not None and v >= prev else ''}{v - prev})" if prev is not None else ""
        print(f"  {k:16} {v}{delta}")
    print(f"  join_status     {js_counts}")
    print(f"  provisional B talk_cards synthesized: {summary.get('provisional_talk_cards_from_b')}")
    print(f"  → {out_dir}")


def reextract_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Attempt / stub prioritized re-extraction")
    ap.add_argument("--limit", type=int, default=10, help="Top-N queue sessions")
    ap.add_argument(
        "--execute",
        action="store_true",
        help="If keys+transcripts exist, mark ready (live API call reserved)",
    )
    args = ap.parse_args(argv)

    queue_path = MASTER / "reextraction_queue.csv"
    if not queue_path.exists():
        print("No reextraction_queue.csv — run triage_unmatched_talks.py first")
        return
    qrows = list(csv.DictReader(open(queue_path, newline="")))
    # Ensure priority sort
    qrows.sort(key=lambda q: (-int(q.get("priority_score") or 0), q["session_slug"]))

    if reextract.has_llm_keys():
        summary = reextract.attempt_limited_reextract(qrows, limit=min(3, args.limit))
        stubs = reextract.write_offline_stubs(qrows, top_n=args.limit)
        print(f"API keys present: prepared attempts → {summary.get('out_dir')}")
        print(f"Also wrote offline stubs → {stubs}")
        if args.execute:
            print(
                "--execute: live OpenRouter call not auto-run here "
                "(transcripts may be off-workspace); stubs + attempt sidecars ready."
            )
    else:
        stubs = reextract.write_offline_stubs(qrows, top_n=args.limit)
        print(f"No API keys — offline stubs only → {stubs}")
