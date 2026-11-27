"""Unmatched Schema B categorization and re-extraction queue builders."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

WEAK_SPEAKER = re.compile(
    r"^(speaker\s*\d*|unknown|dr\.?\s*unknown|moderator|chair|panelist).*$",
    re.I,
)

# Priority for queue ordering (higher = sooner)
REASON_PRIORITY = {
    "no_schema_a": 100,
    "asr_name": 80,
    "unmatched_name": 70,
    "count_mismatch": 50,
    "low_signal": 10,
}


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
        if (
            "panel" in b_speaker.lower()
            or "moderator" in b_speaker.lower()
            or "no original data" in b_title.lower()
        ):
            return "low_signal"
    if leftover_a > 0 and (
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


def session_priority(queue_row: dict) -> int:
    """Higher score → re-extract sooner."""
    reason = queue_row.get("primary_reason") or ""
    base = REASON_PRIORITY.get(reason, 40)
    n_un = int(queue_row.get("n_unmatched_b") or 0)
    blocked = 20 if queue_row.get("blocked_without_schema_a") == "yes" else 0
    return base + n_un * 3 + blocked


def build_triage(
    join_rows: list[dict],
    a_by: dict[str, list],
    b_by: dict[str, list],
    is_valid_b,
) -> tuple[list[dict], list[dict]]:
    """Return (triage_rows, prioritized_queue_rows)."""
    by_slug: dict[str, list[dict]] = defaultdict(list)
    for r in join_rows:
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
                    "blocked_without_llm": "yes"
                    if cat == "no_schema_a" or (cat == "count_mismatch" and len(leftover_a) == 0)
                    else "no",
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
            "priority_score": 0,  # filled below
        }

    qrows = list(queue_sessions.values())
    for q in qrows:
        q["priority_score"] = session_priority(q)
    qrows.sort(key=lambda q: (-q["priority_score"], q["session_slug"]))
    for i, q in enumerate(qrows, start=1):
        q["queue_rank"] = i

    return triage, qrows


def notes_markdown(
    triage: list[dict],
    qrows: list[dict],
    *,
    triage_rel: str,
    queue_rel: str,
    stubs_rel: str | None = None,
    api_attempted: bool = False,
) -> str:
    cat_counts = Counter(t["reason_category"] for t in triage)
    blocked = [q for q in qrows if q["blocked_without_schema_a"] == "yes"]
    lines = [
        "# Re-extraction queue notes",
        "",
        "Offline triage of unmatched Schema B talks after improved join cascade.",
        (
            "OpenRouter / LLM re-extraction was **attempted** for top queue items."
            if api_attempted
            else "OpenRouter / LLM re-extraction was **not** run (keys unavailable). Offline stubs + notes only."
        ),
        "",
        "## Summary",
        "",
        f"- Unmatched B talks: **{len(triage)}** across **{len(qrows)}** sessions",
        f"- Reason categories: `{dict(cat_counts)}`",
        f"- Sessions blocked without Schema A: **{len(blocked)}**",
        "",
        "## Priority order (top 15)",
        "",
        "| Rank | Session | Reason | Unmatched B | Action |",
        "|---|---|---|---|---|",
    ]
    for q in qrows[:15]:
        lines.append(
            f"| {q.get('queue_rank', '')} | `{q['session_slug'][:48]}` | "
            f"{q['primary_reason']} | {q['n_unmatched_b']} | `{q['action']}` |"
        )
    lines += [
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
        "3. Pure `count_mismatch` with zero leftover A means B extracted chairs/panelists A never modeled — "
        "keep as **provisional** embedding units (`join_status=unmatched`) rather than dropping.",
        "4. B-only sessions: provisional talk cards are synthesized from Schema B metadata for index prep.",
        "",
    ]
    if stubs_rel:
        lines.append(f"Offline stubs: `{stubs_rel}`")
        lines.append("")
    lines += [
        f"Artifacts: `{triage_rel}`, `{queue_rel}`.",
        "",
    ]
    return "\n".join(lines)
