#!/usr/bin/env python3
"""
Repair Schema B talk_id joins to Schema A.

Root cause: extractor_v{3-6} rewrites talk_id via rec["speaker"]["name"], but
Schema B stores the name at talk_metadata.speaker_name — so nearly all B IDs
became session::unknown::N.

Also drops orphan nested objects that leaked into the Schema B array
(e.g. advances-in-therapeutic-antibodies: 45 non-talk fragments).

Usage:
  python3 scripts/repair_talk_id_joins.py          # dry-run stats
  python3 scripts/repair_talk_id_joins.py --write  # mutate extractions + masters
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR_A = ROOT / "extractions" / "schema_a"
DIR_B = ROOT / "extractions" / "schema_b"
MASTER = ROOT / "data" / "master"


def last_name(name: str | None) -> str:
    if not name:
        return "unknown"
    n = re.sub(r"\b(MD|PhD|Dr|Professor|Prof|Ms|Mr|Mrs)\b\.?", "", name, flags=re.I)
    n = re.sub(r"[^A-Za-z\-\s]", " ", n)
    parts = [p for p in n.strip().split() if len(p) > 1]
    return parts[-1].lower() if parts else "unknown"


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())).strip()


def sim(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def is_valid_b(rec: dict) -> bool:
    md = rec.get("talk_metadata")
    if isinstance(md, dict) and (md.get("speaker_name") or md.get("talk_title")):
        return True
    speaker = rec.get("speaker")
    if isinstance(speaker, dict) and speaker.get("name"):
        return True
    return False


def b_speaker_name(rec: dict) -> str:
    md = rec.get("talk_metadata") or {}
    if md.get("speaker_name"):
        return md["speaker_name"]
    speaker = rec.get("speaker") or {}
    return speaker.get("name") or ""


def b_talk_title(rec: dict) -> str:
    md = rec.get("talk_metadata") or {}
    return md.get("talk_title") or rec.get("talk_title") or ""


def cascade_join(A: list[dict], B: list[dict]) -> list[tuple[int | None, str]]:
    """Return per-B-record (a_index_or_None, method)."""
    used: set[int] = set()
    by_ln: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(A):
        by_ln[last_name((a.get("speaker") or {}).get("name"))].append(i)

    results: list[tuple[int | None, str]] = []
    pending_b: list[int] = []

    for bi, b in enumerate(B):
        name = b_speaker_name(b)
        ln = last_name(name)
        title = b_talk_title(b)
        ai = None
        method = "unmatched"

        cands = [i for i in by_ln.get(ln, []) if i not in used]
        if not cands and ln != "unknown":
            for k, idxs in by_ln.items():
                if k != "unknown" and sim(k, ln) >= 0.85:
                    cands = [i for i in idxs if i not in used]
                    if cands:
                        break

        if len(cands) == 1:
            ai, method = cands[0], "name"
        elif len(cands) > 1:
            scored = sorted(((sim(A[i].get("talk_title"), title), i) for i in cands), reverse=True)
            if scored[0][0] >= 0.35:
                ai, method = scored[0][1], "name_title"

        if ai is None:
            scored = sorted(
                ((sim(A[i].get("talk_title"), title), i) for i in range(len(A)) if i not in used),
                reverse=True,
            )
            if scored and scored[0][0] >= 0.55:
                ai, method = scored[0][1], "title"

        if ai is not None:
            used.add(ai)
            results.append((ai, method))
        else:
            pending_b.append(bi)
            results.append((None, "unmatched"))

    leftover_a = [i for i in range(len(A)) if i not in used]
    if leftover_a and len(leftover_a) == len(pending_b):
        for ai, bi in zip(leftover_a, pending_b):
            results[bi] = (ai, "order")
            used.add(ai)

    return results


def load_sessions() -> tuple[dict[str, list], dict[str, list]]:
    a_by, b_by = {}, {}
    for f in DIR_A.glob("*.json"):
        a_by[f.stem] = json.load(open(f))
    for f in DIR_B.glob("*.json"):
        b_by[f.stem] = json.load(open(f))
    return a_by, b_by


def rewrite_b_talk_id(slug: str, rec: dict, index: int, canonical: str | None) -> str:
    if canonical:
        return canonical
    ln = last_name(b_speaker_name(rec))
    return f"{slug}::{ln}::{index}"


def remap_csv(path: Path, id_map: dict[str, str]) -> int:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Write repaired files")
    args = ap.parse_args()

    a_by, b_by = load_sessions()
    join_rows = []
    id_map: dict[str, str] = {}
    methods = defaultdict(int)
    orphans_dropped = 0
    repaired_sessions = 0

    for slug in sorted(set(a_by) | set(b_by)):
        A = a_by.get(slug, [])
        raw_B = b_by.get(slug, [])
        valid_B = [r for r in raw_B if is_valid_b(r)]
        orphans_dropped += len(raw_B) - len(valid_B)

        if not raw_B:
            continue

        pairs = cascade_join(A, valid_B) if A else [(None, "no_schema_a")] * len(valid_B)
        new_records = []
        for bi, (ai, method) in enumerate(pairs):
            rec = valid_B[bi]
            old_id = rec.get("talk_id") or ""
            canonical = A[ai]["talk_id"] if ai is not None else None
            # Prefer A's index in the id when joined; else 1-based among valid B
            new_id = rewrite_b_talk_id(slug, rec, (ai + 1) if ai is not None else (bi + 1), canonical)
            methods[method] += 1
            join_rows.append(
                {
                    "session_slug": slug,
                    "method": method,
                    "old_talk_id": old_id,
                    "new_talk_id": new_id,
                    "a_speaker": ((A[ai].get("speaker") or {}).get("name") if ai is not None else ""),
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

    # Stats
    joined = sum(1 for r in join_rows if r["joined"] == "yes")
    print("Schema B repair summary")
    print(f"  valid B rows processed : {len(join_rows)}")
    print(f"  orphan fragments drop  : {orphans_dropped}")
    print(f"  joined to Schema A     : {joined} ({joined / max(len(join_rows), 1):.1%})")
    print(f"  unmatched B            : {len(join_rows) - joined}")
    print(f"  methods                : {dict(methods)}")
    print(f"  talk_id remaps         : {len(id_map)}")

    map_path = MASTER / "talk_id_join_map.csv"
    if args.write:
        with open(map_path, "w", newline="") as f:
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
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(join_rows)
        print(f"  wrote {map_path}")

        # Rebuild schema_b_master.json + .csv from repaired files
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
                        v.get("failing_compound_or_target", "") for v in vulns if isinstance(v, dict)
                    ),
                    "mechanistic_blindspot": ";".join(
                        (v.get("mechanistic_blindspot") or "") for v in vulns if isinstance(v, dict)
                    ),
                    "evidence_strength": ";".join(
                        (v.get("evidence_strength") or "") for v in vulns if isinstance(v, dict)
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
        fields = list(old_fields or csv_rows[0].keys())
        for k in csv_rows[0].keys():
            if k not in fields:
                fields.append(k)
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(csv_rows)
        print(f"  wrote schema_b_master.csv ({len(csv_rows)} rows)")

        # Remap dependent CSVs by old→new talk_id
        for name in [
            "crispro_opportunities_all.csv",
            "cognitive_dissonance_all.csv",
        ]:
            n = remap_csv(MASTER / name, id_map)
            print(f"  remapped {name}: {n} talk_ids")

        print(f"  repaired schema_b sessions: {repaired_sessions}")
    else:
        print("  dry-run only (pass --write to mutate files)")
        # still write map preview under /tmp? skip
        with open(map_path, "w", newline="") as f:
            fields = list(join_rows[0].keys()) if join_rows else []
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(join_rows)
        print(f"  wrote join map preview → {map_path}")


if __name__ == "__main__":
    main()
