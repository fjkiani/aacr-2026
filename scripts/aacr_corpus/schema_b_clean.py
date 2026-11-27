"""Schema B orphan-fragment filter and field accessors."""
from __future__ import annotations


def is_valid_b(rec: dict) -> bool:
    """Keep only top-level talk records; drop nested fragment objects."""
    md = rec.get("talk_metadata")
    if isinstance(md, dict) and (md.get("speaker_name") or md.get("talk_title")):
        return True
    speaker = rec.get("speaker")
    if isinstance(speaker, dict) and speaker.get("name"):
        return True
    return False


def filter_valid_b(records: list[dict]) -> tuple[list[dict], int]:
    """Return (valid_records, orphans_dropped)."""
    valid = [r for r in records if is_valid_b(r)]
    return valid, len(records) - len(valid)


def b_speaker_name(rec: dict) -> str:
    md = rec.get("talk_metadata") or {}
    if md.get("speaker_name"):
        return md["speaker_name"]
    speaker = rec.get("speaker") or {}
    return speaker.get("name") or ""


def b_talk_title(rec: dict) -> str:
    md = rec.get("talk_metadata") or {}
    return md.get("talk_title") or rec.get("talk_title") or ""


def b_institution(rec: dict) -> str:
    md = rec.get("talk_metadata") or {}
    return md.get("institution_or_pharma") or ""


def a_speaker_name(rec: dict) -> str:
    return (rec.get("speaker") or {}).get("name") or ""


def a_affiliation(rec: dict) -> str:
    sp = rec.get("speaker") or {}
    return sp.get("affiliation") or sp.get("institution") or ""
