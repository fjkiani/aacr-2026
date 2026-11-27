"""Prioritized re-extraction: limited API pass if keys exist, else offline stubs."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .paths import DIR_A, DIR_B, MASTER, REEXTRACT_STUBS, ROOT


def openrouter_keys() -> list[str]:
    keys = []
    for name in (
        "OPENROUTER_KEY_1",
        "OPENROUTER_KEY_2",
        "OPENROUTER_API_KEY",
        "OPENROUTER_KEY",
    ):
        v = (os.environ.get(name) or "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys


def has_llm_keys() -> bool:
    return bool(openrouter_keys())


def write_offline_stubs(
    queue_rows: list[dict],
    *,
    top_n: int = 10,
    out_dir: Path | None = None,
) -> Path:
    """
    Rich offline stubs for top-priority sessions: capture B (and A if any)
    payloads + extraction brief so a later LLM pass has context without keys now.
    """
    out_dir = out_dir or REEXTRACT_STUBS
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for q in queue_rows[:top_n]:
        slug = q["session_slug"]
        a_path = DIR_A / f"{slug}.json"
        b_path = DIR_B / f"{slug}.json"
        a_data = json.load(open(a_path)) if a_path.exists() else []
        b_data = json.load(open(b_path)) if b_path.exists() else []
        stub = {
            "session_slug": slug,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "offline_stub",
            "queue": q,
            "schema_a_present": bool(a_data),
            "n_schema_a": len(a_data),
            "n_schema_b": len(b_data),
            "schema_a": a_data,
            "schema_b": b_data,
            "extractor_guidance": {
                "use_patched_v6_patterns": True,
                "speaker_name_paths": ["speaker.name", "talk_metadata.speaker_name"],
                "filter_orphan_fragments": True,
                "align_ab_in_one_call": q.get("action") != "extract_schema_a_missing",
                "goal": (
                    "Extract missing Schema A talks for this B-only session"
                    if q.get("blocked_without_schema_a") == "yes"
                    else "Re-extract aligned Schema A+B so talk_ids match; drop chair-only B extras or mark provisional"
                ),
            },
            "unmatched_speakers": [
                s.strip() for s in (q.get("unmatched_b_speakers") or "").split(";") if s.strip()
            ],
        }
        path = out_dir / f"{slug}.stub.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stub, f, indent=2, ensure_ascii=False)
            f.write("\n")
        written.append(path.name)

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_stub",
        "api_keys_present": False,
        "top_n": top_n,
        "stubs": written,
        "note": (
            "No OpenRouter/API keys in env. Stubs hold current A/B payloads + guidance "
            "for a later limited re-extract with patched extractor_v6 patterns."
        ),
    }
    index_path = out_dir / "INDEX.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

    notes = MASTER / "reextraction_offline_notes.md"
    lines = [
        "# Offline re-extraction stubs",
        "",
        f"Generated: `{index['generated_at']}`",
        "",
        "No LLM API keys detected (`OPENROUTER_KEY_*` / `OPENROUTER_API_KEY`).",
        f"Wrote **{len(written)}** session stubs under "
        f"`{out_dir.relative_to(ROOT)}/` for the top prioritized queue items.",
        "",
        "## Stub contents",
        "",
        "- Current Schema A/B JSON (if present)",
        "- Queue metadata (reason, unmatched speakers, action)",
        "- Extractor guidance (patched v6 speaker paths + orphan filter)",
        "",
        "## Top stubs",
        "",
    ]
    for name, q in zip(written, queue_rows[:top_n]):
        lines.append(
            f"- `{name}` — `{q['primary_reason']}` / `{q['action']}` "
            f"({q['n_unmatched_b']} unmatched B)"
        )
    lines += [
        "",
        "When keys are available: run `python3 scripts/attempt_reextraction.py --limit N` "
        "to attempt limited live re-extract of top queue sessions.",
        "",
    ]
    notes.write_text("\n".join(lines), encoding="utf-8")
    return out_dir


def attempt_limited_reextract(
    queue_rows: list[dict],
    *,
    limit: int = 3,
) -> dict:
    """
    If OpenRouter keys exist, attempt a limited re-extract for top sessions.
    Returns a result dict; does not wipe existing extractions without writing a sidecar.
    """
    keys = openrouter_keys()
    if not keys:
        return {
            "attempted": False,
            "reason": "no_api_keys",
            "stubs_dir": str(write_offline_stubs(queue_rows)),
        }

    # Live path is intentionally conservative: we only prepare request payloads
    # and record that keys exist. Full extractor_v6 depends on /mnt/results
    # transcripts which may be absent in this workspace.
    out_dir = MASTER / "reextraction_attempts"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    transcript_root_candidates = [
        Path("/mnt/results/aacr2026/transcripts"),
        ROOT / "transcripts",
        ROOT / "data" / "transcripts",
    ]
    tx_dir = next((p for p in transcript_root_candidates if p.exists()), None)

    for q in queue_rows[:limit]:
        slug = q["session_slug"]
        tx = (tx_dir / f"{slug}.txt") if tx_dir else None
        entry = {
            "session_slug": slug,
            "queue_rank": q.get("queue_rank"),
            "action": q.get("action"),
            "transcript_found": bool(tx and tx.exists()),
            "status": "skipped_no_transcript" if not (tx and tx.exists()) else "ready_for_api",
        }
        if tx and tx.exists():
            # Do not auto-call paid/free APIs without an explicit --execute flag in CLI.
            entry["status"] = "prepared_not_executed"
            entry["transcript_chars"] = tx.stat().st_size
            entry["note"] = (
                "Keys present and transcript found. Pass --execute on "
                "attempt_reextraction.py to call OpenRouter (uses patched speaker paths)."
            )
        results.append(entry)
        with open(out_dir / f"{slug}.attempt.json", "w") as f:
            json.dump(entry, f, indent=2)
            f.write("\n")

    summary = {
        "attempted": True,
        "executed": False,
        "keys_present": True,
        "limit": limit,
        "results": results,
        "out_dir": str(out_dir.relative_to(ROOT)),
    }
    with open(out_dir / "SUMMARY.json", "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    return summary
