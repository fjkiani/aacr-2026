"""Claim-level embedding unit builders — joined, unmatched, and provisional."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from .paths import MASTER
from .schema_b_clean import b_speaker_name, b_talk_title, is_valid_b


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


def load_join_status() -> dict[str, str]:
    """
    Map talk_id → join_status.

    joined      — B row matched to Schema A
    unmatched   — B row present but not joined (count_mismatch / asr / etc.)
    provisional — B-only session (no Schema A) or synthetic card from B
    """
    path = MASTER / "talk_id_join_map.csv"
    status: dict[str, str] = {}
    if not path.exists():
        return status
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            tid = row.get("new_talk_id") or ""
            if not tid:
                continue
            if row.get("joined") == "yes":
                status[tid] = "joined"
            elif row.get("method") == "no_schema_a":
                status[tid] = "provisional"
            else:
                status[tid] = "unmatched"
            old = row.get("old_talk_id") or ""
            if old and old not in status:
                status[old] = status[tid]
    return status


def load_joined_ids(status: dict[str, str] | None = None) -> set[str]:
    status = status or load_join_status()
    return {tid for tid, s in status.items() if s == "joined"}


def quality_flags(
    *,
    join_status: str,
    speaker: str,
    has_evidence: bool,
    has_entity: bool,
    unknown_speaker: bool = False,
) -> dict:
    return {
        "join_status": join_status,
        "has_evidence": has_evidence,
        "has_entity": has_entity,
        "unknown_speaker": unknown_speaker,
        "provisional": join_status in {"unmatched", "provisional"},
        "indexable": has_evidence and has_entity and not (
            unknown_speaker and join_status == "joined"
        ),
    }


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


def _resolve_status(talk_id: str, status: dict[str, str], *, default: str = "schema_a_native") -> str:
    return status.get(talk_id, default)


def talk_id_gate(
    talk_id: str,
    status: dict[str, str],
    *,
    allow_provisional: bool,
    allow_schema_a_unknown: bool = False,
) -> tuple[bool, str]:
    """Return (ok_to_emit, join_status)."""
    if not talk_id or "::" not in talk_id:
        return False, "invalid"
    js = _resolve_status(talk_id, status)
    if "::unknown::" in talk_id:
        if allow_schema_a_unknown and js in {"joined", "schema_a_native"}:
            return True, js if js != "schema_a_native" else "joined"
        if allow_provisional and js in {"unmatched", "provisional"}:
            return True, js
        return False, js
    if js == "joined":
        return True, "joined"
    if js in {"unmatched", "provisional"}:
        return allow_provisional, js
    # Schema A native (never on B join map)
    return True, "joined"


def build_talk_cards(
    status: dict[str, str],
    *,
    allow_provisional: bool = True,
) -> tuple[list[dict], Counter]:
    data = json.load(open(MASTER / "schema_a_master.json"))
    out = []
    skip = Counter()
    for rec in data:
        talk_id = rec.get("talk_id") or ""
        ok, js = talk_id_gate(
            talk_id, status, allow_provisional=allow_provisional, allow_schema_a_unknown=True
        )
        if not ok:
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

        has_ev = nonempty(moa) or nonempty(findings_txt)
        if not has_ev:
            skip["no_evidence"] += 1
            continue
        unknown_spk = speaker.lower() == "unknown"
        if unknown_spk and not nonempty(targets_txt):
            skip["low_signal_unknown"] += 1
            continue
        has_ent = (
            nonempty(speaker)
            or nonempty(targets_txt)
            or nonempty(tumors_txt)
            or nonempty(rec.get("talk_title"))
        )
        if not has_ent:
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
        qf = quality_flags(
            join_status=js,
            speaker=speaker,
            has_evidence=has_ev,
            has_entity=has_ent,
            unknown_speaker=unknown_spk,
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
                    **qf,
                },
                source="schema_a_master.json",
            )
        )
    return out, skip


def build_provisional_talk_cards_from_b(
    status: dict[str, str],
) -> tuple[list[dict], Counter]:
    """
    Synthesize talk cards for B-only / unmatched B rows that lack Schema A cards.
    Prefer provisional (no_schema_a) sessions; also cover unmatched extras with signal.
    """
    data = json.load(open(MASTER / "schema_b_master.json"))
    a_ids = set()
    a_path = MASTER / "schema_a_master.json"
    if a_path.exists():
        a_ids = {r.get("talk_id") for r in json.load(open(a_path)) if r.get("talk_id")}

    out = []
    skip = Counter()
    for rec in data:
        if not is_valid_b(rec):
            continue
        talk_id = rec.get("talk_id") or ""
        js = status.get(talk_id)
        if js not in {"provisional", "unmatched"}:
            skip["already_joined_or_native"] += 1
            continue
        # Avoid duplicate card when Schema A already has this id
        if talk_id in a_ids:
            skip["schema_a_exists"] += 1
            continue

        md = rec.get("talk_metadata") or {}
        speaker = b_speaker_name(rec)
        title = b_talk_title(rec)
        inst = md.get("institution_or_pharma") or ""
        session = md.get("session_title") or ""
        cd = rec.get("cognitive_dissonance") or []
        opps = rec.get("crispro_opportunity") or []
        vulns = rec.get("vulnerability_identified") or []

        cd_txt = "; ".join(
            (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)) for c in cd[:2] if c
        )
        opp_bits = []
        for o in opps[:2]:
            if isinstance(o, dict):
                opp_bits.append(o.get("description") or o.get("crispro_angle") or "")
            elif o:
                opp_bits.append(str(o))
        opp_txt = "; ".join(x for x in opp_bits if x)

        has_ev = nonempty(title) or nonempty(cd_txt) or nonempty(opp_txt) or nonempty(vulns)
        if not has_ev:
            skip["no_evidence"] += 1
            continue
        unknown_spk = speaker.lower() in {"", "unknown"} or speaker.lower().startswith("dr. unknown")
        has_ent = nonempty(speaker) or nonempty(title) or nonempty(session)
        if not has_ent:
            skip["no_entity"] += 1
            continue
        if unknown_spk and not (nonempty(title) or nonempty(cd_txt)):
            skip["low_signal_unknown"] += 1
            continue

        text = " | ".join(
            x
            for x in [
                title,
                f"Speaker: {speaker}" if nonempty(speaker) else "",
                f"Institution: {inst}" if nonempty(inst) else "",
                f"Session: {session}" if nonempty(session) else "",
                f"CD: {cd_txt}" if cd_txt else "",
                f"CrisPRO: {opp_txt}" if opp_txt else "",
                "[provisional — no Schema A join]" if js == "provisional" else "[unmatched B]",
            ]
            if x
        )
        qf = quality_flags(
            join_status=js,
            speaker=speaker,
            has_evidence=True,
            has_entity=has_ent,
            unknown_speaker=unknown_spk,
        )
        out.append(
            unit(
                unit_type="talk_card",
                talk_id=talk_id,
                text=text,
                metadata={
                    "speaker": speaker,
                    "session_title": session,
                    "talk_title": title,
                    "institution": inst,
                    "presentation_type": md.get("presentation_type"),
                    "synthesized_from": "schema_b",
                    "n_cd": len(cd),
                    "n_opps": len(opps),
                    "n_vulns": len(vulns),
                    **qf,
                },
                source="schema_b_master.json#provisional_talk_card",
            )
        )
    return out, skip


def build_clinical(
    status: dict[str, str],
    *,
    allow_provisional: bool = True,
) -> tuple[list[dict], Counter]:
    path = MASTER / "clinical_data_all.csv"
    out = []
    skip = Counter()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            talk_id = row.get("talk_id") or ""
            ok, js = talk_id_gate(
                talk_id, status, allow_provisional=allow_provisional, allow_schema_a_unknown=True
            )
            if not ok:
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
            if speaker.lower() == "unknown" and not nonempty(tumor) and js == "joined":
                skip["low_signal_unknown"] += 1
                continue
            has_ent = nonempty(speaker) or nonempty(tumor) or nonempty(metric)
            if not has_ent:
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
            qf = quality_flags(
                join_status=js,
                speaker=speaker,
                has_evidence=True,
                has_entity=has_ent,
                unknown_speaker=speaker.lower() == "unknown",
            )
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
                        **qf,
                    },
                    source="clinical_data_all.csv",
                )
            )
    return out, skip


def build_crispro(
    status: dict[str, str],
    *,
    allow_provisional: bool = True,
) -> tuple[list[dict], Counter]:
    path = MASTER / "crispro_opportunities_all.csv"
    out = []
    skip = Counter()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            talk_id = row.get("talk_id") or ""
            # Residual A/B unknowns still carry real intel — emit with quality flags
            # (indexable=false when unknown_speaker + joined).
            ok, js = talk_id_gate(
                talk_id,
                status,
                allow_provisional=allow_provisional,
                allow_schema_a_unknown=True,
            )
            if not ok:
                skip["bad_talk_id"] += 1
                continue
            desc = (row.get("description") or "").strip()
            evidence = (row.get("transcript_evidence") or "").strip()
            angle = (row.get("crispro_angle") or "").strip()
            if not desc or not evidence:
                skip["no_evidence"] += 1
                continue
            speaker = row.get("speaker_name") or ""
            otype = row.get("opportunity_type") or ""
            unknown_spk = (
                speaker.lower().startswith("dr. unknown")
                or speaker.lower() == "unknown"
                or "::unknown::" in talk_id
            )
            # Keep joined unknowns when opportunity type or descriptive speaker label exists
            if unknown_spk and js == "joined" and not (nonempty(otype) or nonempty(speaker)):
                skip["low_signal_unknown"] += 1
                continue
            has_ent = nonempty(speaker) or nonempty(otype) or nonempty(desc)
            if not has_ent:
                skip["no_entity"] += 1
                continue
            text = " | ".join(x for x in [desc, angle, evidence] if x)
            qf = quality_flags(
                join_status=js,
                speaker=speaker,
                has_evidence=True,
                has_entity=has_ent,
                unknown_speaker=unknown_spk,
            )
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
                        **qf,
                    },
                    source="crispro_opportunities_all.csv",
                )
            )
    return out, skip


def build_cd_and_vuln(
    status: dict[str, str],
    *,
    allow_provisional: bool = True,
) -> tuple[list[dict], list[dict], Counter, Counter]:
    data = json.load(open(MASTER / "schema_b_master.json"))
    cd_out, vuln_out = [], []
    skip_cd, skip_v = Counter(), Counter()
    for rec in data:
        talk_id = rec.get("talk_id") or ""
        md = rec.get("talk_metadata") or {}
        speaker = md.get("speaker_name") or ""
        ok, js = talk_id_gate(
            talk_id,
            status,
            allow_provisional=allow_provisional,
            allow_schema_a_unknown=True,
        )
        unknown_spk = (
            speaker.lower().startswith("dr. unknown")
            or speaker.lower() == "unknown"
            or "::unknown::" in talk_id
        )

        for cd in rec.get("cognitive_dissonance") or []:
            if not ok:
                skip_cd["bad_talk_id"] += 1
                continue
            text = cd if isinstance(cd, str) else json.dumps(cd, ensure_ascii=False)
            if not nonempty(text) or len(text) < 40:
                skip_cd["no_evidence"] += 1
                continue
            has_ent = nonempty(speaker) or nonempty(md.get("talk_title"))
            if not has_ent:
                skip_cd["no_entity"] += 1
                continue
            # Joined unknowns keep CD text; quality_flags mark indexable=false
            qf = quality_flags(
                join_status=js,
                speaker=speaker,
                has_evidence=True,
                has_entity=has_ent,
                unknown_speaker=unknown_spk,
            )
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
                        **qf,
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
            has_ent = (
                nonempty(speaker)
                or nonempty(v.get("failing_compound_or_target"))
                or nonempty(v.get("failure_type"))
            )
            if not has_ent:
                skip_v["no_entity"] += 1
                continue
            qf = quality_flags(
                join_status=js,
                speaker=speaker,
                has_evidence=True,
                has_entity=has_ent,
                unknown_speaker=unknown_spk,
            )
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
                        **qf,
                    },
                    source="schema_b_master.json",
                )
            )
    return cd_out, vuln_out, skip_cd, skip_v


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def count_by_join_status(units: list[dict]) -> dict[str, int]:
    c = Counter()
    for u in units:
        js = (u.get("metadata") or {}).get("join_status") or "unknown"
        c[js] += 1
    return dict(c)


def build_all(
    *,
    allow_provisional: bool = True,
) -> tuple[dict[str, list[dict]], dict]:
    status = load_join_status()
    talk_cards, skip_tc = build_talk_cards(status, allow_provisional=allow_provisional)
    prov_cards, skip_prov = build_provisional_talk_cards_from_b(status)
    # Dedup talk cards by talk_id (Schema A wins)
    seen_tc = {u["talk_id"] for u in talk_cards}
    for u in prov_cards:
        if u["talk_id"] not in seen_tc:
            talk_cards.append(u)
            seen_tc.add(u["talk_id"])
        else:
            skip_prov["dup_schema_a"] += 1

    clinical, skip_cl = build_clinical(status, allow_provisional=allow_provisional)
    crispro, skip_cr = build_crispro(status, allow_provisional=allow_provisional)
    cd_hits, vulns, skip_cd, skip_v = build_cd_and_vuln(
        status, allow_provisional=allow_provisional
    )

    bundles = {
        "talk_card": talk_cards,
        "clinical_fact": clinical,
        "crispro_opp": crispro,
        "cd_hit": cd_hits,
        "vulnerability": vulns,
    }
    all_units = talk_cards + clinical + crispro + cd_hits + vulns
    summary = {
        "counts": {k: len(v) for k, v in bundles.items()} | {"total": len(all_units)},
        "join_status_counts": count_by_join_status(all_units),
        "provisional_talk_cards_from_b": len(prov_cards),
        "skips": {
            "talk_card": dict(skip_tc),
            "provisional_talk_card": dict(skip_prov),
            "clinical_fact": dict(skip_cl),
            "crispro_opp": dict(skip_cr),
            "cd_hit": dict(skip_cd),
            "vulnerability": dict(skip_v),
        },
        "joined_talk_ids": len(load_joined_ids(status)),
        "status_talk_ids": {
            "joined": sum(1 for s in status.values() if s == "joined"),
            "unmatched": sum(1 for s in status.values() if s == "unmatched"),
            "provisional": sum(1 for s in status.values() if s == "provisional"),
        },
        "allow_provisional": allow_provisional,
        "schema": {
            "id": "stable unit id",
            "unit_type": "talk_card|clinical_fact|crispro_opp|cd_hit|vulnerability",
            "talk_id": "canonical Schema A talk_id when joined; B-derived when provisional",
            "text": "string to embed",
            "metadata": "filterable fields incl. join_status + quality flags",
            "source": "origin master file",
        },
    }
    return bundles, summary
