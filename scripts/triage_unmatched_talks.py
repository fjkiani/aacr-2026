#!/usr/bin/env python3
"""
Triage Schema B talks that failed A↔B join.

Reads data/master/talk_id_join_map.csv (+ schema A/B extractions) and writes:
  - data/master/unmatched_talk_triage.csv
  - data/master/reextraction_queue.csv
  - data/master/reextraction_queue_notes.md

No LLM / OpenRouter required — offline classification only.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "master"
DIR_A = ROOT / "extractions" / "schema_a"
DIR_B = ROOT / "extractions" / "schema_b"

WEAK_SPEAKER = re.compile(
    r"^(speaker\s*\d*|unknown|dr\.?\s*unknown|moderator|chair|panelist).*$",
    re.I,
)


def is_valid_b(rec: dict) -> bool:
    md = rec.get("talk_metadata")
    if isinstance(md, dict) and (md.get("speaker_name") or md.get("talk_title")):
        return True
    speaker = rec.get("speaker")
    if isinstance(speaker, dict) and speaker.get("name"):
        return True
    return False


def classify_row(
    row: dict,
    n_a: int,
    n_b: int,
    leftover_a: int,
) -> str:
    method = row.get("method") or ""
    b_speaker = (row.get("b_speaker") or "").strip()
    b_title = (row.get("b_talk_title") or "").strip()

    if method == "no_schema_a" or n_a == 0:
        return "no_schema_a"
    if WEAK_SPEAKER.match(b_speaker) or not b_speaker:
        return "low_signal"
    if not b_title or b_title.lower() in {"panel discussion", "panel discussion (no original data)"}:
        if "panel" in b_speaker.lower() or "moderator" in b_speaker.lower() or "no original data" in b_title.lower():
            return "low_signal"
    if leftover_a > 0 and (
        # likely ASR / partial name if A still has unused speakers
        len(b_speaker.split()) <= 1
        or "[" in b_speaker
        or "lastname" in b_speaker.lower()
    ):
        return "asr_name"
    if leftover_a > 0:
        return "asr_name"
    if n_a != n_b:
        return "count_mismatch"
    return "unmatched_name"


def main() -> None:
    map_path = MASTER / "talk_id_join_map.csv"
    rows = list(csv.DictReader(open(map_path, newline="")))

    a_by = {f.stem: json.load(open(f)) for f in DIR_A.glob("*.json")}
    b_by = {f.stem: json.load(open(f)) for f in DIR_B.glob("*.json")}

    by_slug: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_slug[r["session_slug"]].append(r)

    triage: list[dict] = []
    queue_sessions: dict[str, dict] = {}

    for slug, rs in sorted(by_slug.items()):
        un = [r for r in rs if r["joined"] == "no"]
        if not un:
            continue
        A = a_by.get(slug, [])
        raw_B = b_by.get(slug, [])
        valid_B = [r for r in raw_B if is_valid_b(r)]
        used = {r["new_talk_id"] for r in rs if r["joined"] == "yes"}
        leftover_a = [a for a in A if a.get("talk_id") not in used]
        n_a, n_b = len(A), len(valid_B)
        joined_yes = sum(1 for r in rs if r["joined"] == "yes")

        for r in un:
            cat = classify_row(r, n_a, n_b, len(leftover_a))
            triage.append(
                {
                    "session_slug": slug,
                    "reason_category": cat,
                    "method": r.get("method", ""),
                    "b_speaker": r.get("b_speaker", ""),
                    "b_talk_title": r.get("b_talk_title", ""),
                    "a_speaker": r.get("a_speaker", ""),
                    "a_talk_title": r.get("a_talk_title", ""),
                    "old_talk_id": r.get("old_talk_id", ""),
                    "new_talk_id": r.get("new_talk_id", ""),
                    "n_schema_a": n_a,
                    "n_schema_b_valid": n_b,
                    "n_joined": joined_yes,
                    "n_leftover_a": len(leftover_a),
                    "leftover_a_speakers": "; ".join(
                        (a.get("speaker") or {}).get("name") or "" for a in leftover_a[:8]
                    ),
                    "needs_reextraction": "yes"
                    if cat in {"no_schema_a", "count_mismatch", "asr_name", "unmatched_name"}
                    else "maybe",
                    "blocked_without_llm": "yes" if cat == "no_schema_a" or (cat == "count_mismatch" and len(leftover_a) == 0) else "no",
                }
            )

        cats = Counter(t["reason_category"] for t in triage if t["session_slug"] == slug)
        primary = cats.most_common(1)[0][0]
        queue_sessions[slug] = {
            "session_slug": slug,
            "primary_reason": primary,
            "n_unmatched_b": len(un),
            "n_schema_a": n_a,
            "n_schema_b_valid": n_b,
            "n_joined": joined_yes,
            "n_leftover_a": len(leftover_a),
            "blocked_without_schema_a": "yes" if n_a == 0 else "no",
            "action": (
                "extract_schema_a_missing"
                if n_a == 0
                else "reextract_aligned_ab"
                if len(leftover_a) == 0
                else "reextract_or_manual_asr_resolve"
            ),
            "unmatched_b_speakers": "; ".join(r.get("b_speaker", "") for r in un),
        }

    triage_path = MASTER / "unmatched_talk_triage.csv"
    fields = list(triage[0].keys()) if triage else []
    with open(triage_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(triage)

    queue_path = MASTER / "reextraction_queue.csv"
    qrows = list(queue_sessions.values())
    qfields = list(qrows[0].keys()) if qrows else []
    with open(queue_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=qfields)
        w.writeheader()
        w.writerows(qrows)

    cat_counts = Counter(t["reason_category"] for t in triage)
    blocked = [q for q in qrows if q["blocked_without_schema_a"] == "yes"]
    notes = MASTER / "reextraction_queue_notes.md"
    lines = [
        "# Re-extraction queue notes",
        "",
        "Offline triage of unmatched Schema B talks after improved join cascade.",
        "OpenRouter / LLM re-extraction was **not** run (keys unavailable / not required for this pass).",
        "",
        "## Summary",
        "",
        f"- Unmatched B talks: **{len(triage)}** across **{len(qrows)}** sessions",
        f"- Reason categories: `{dict(cat_counts)}`",
        f"- Sessions blocked without Schema A: **{len(blocked)}**",
        "",
        "## Blocked sessions (need Schema A extraction first)",
        "",
    ]
    for q in blocked:
        lines.append(
            f"- `{q['session_slug']}` — {q['n_unmatched_b']} B talks, speakers: {q['unmatched_b_speakers']}"
        )
    lines += [
        "",
        "## Actions for remaining sessions",
        "",
        "1. Prefer one LLM call that emits **aligned A+B** for the session so IDs are assigned together.",
        "2. For `asr_name` with leftover A speakers, a human pass matching names is often enough (no full re-extract).",
        "3. Pure `count_mismatch` with zero leftover A means B extracted chairs/panelists A never modeled — drop or quarantine those B rows for embedding.",
        "",
        f"Artifacts: `{triage_path.relative_to(ROOT)}`, `{queue_path.relative_to(ROOT)}`.",
        "",
    ]
    notes.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {triage_path} ({len(triage)} rows)")
    print(f"wrote {queue_path} ({len(qrows)} sessions)")
    print(f"wrote {notes}")
    print(f"categories: {dict(cat_counts)}")


if __name__ == "__main__":
    main()
