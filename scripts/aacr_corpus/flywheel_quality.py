"""Flywheel SFT quality gates and synthetic preference-reject generation."""
from __future__ import annotations

import copy
import json
import random
import re
from collections import Counter

EXPECTED_SFT_KEYS = ("moa_summary", "key_findings", "novelty_flag", "clinical_stage")
EXPECTED_PREF_KEYS = (
    "cognitive_dissonance",
    "crispro_opportunity",
    "vulnerability_identified",
    "data_maturity",
)

FAILURE_MODES = (
    "hallucinated_opp",
    "missing_quote",
    "wrong_talk_id",
    "empty_arrays_on_rich_talk",
)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def parse_json_field(obj):
    if isinstance(obj, (dict, list)):
        return obj
    if not isinstance(obj, str):
        return {}
    try:
        return json.loads(obj)
    except json.JSONDecodeError:
        return {}


def nonempty_text(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip()) and v.strip().lower() not in {"unknown", "n/a", "none", "unspecified"}
    if isinstance(v, list):
        return any(nonempty_text(x) for x in v)
    if isinstance(v, dict):
        return any(nonempty_text(x) for x in v.values())
    return True


def has_evidence_quote(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    return "speaker said" in t or bool(re.search(r'"[^"]{20,}"', text))


def score_sft_row(row: dict, a_ids: set[str], joined_ids: set[str]) -> tuple[float, dict]:
    prompt = parse_json_field(row.get("prompt_json"))
    resp = parse_json_field(row.get("remote_response_json"))
    talk_id = (prompt.get("talk_id") or "").strip()
    moa = resp.get("moa_summary") or ""
    findings = resp.get("key_findings") or []
    if not isinstance(findings, list):
        findings = [findings] if findings else []
    tumors = prompt.get("tumor_types") or []
    affiliation = str(prompt.get("affiliation") or "")
    speaker = str(prompt.get("speaker") or "")
    stage = str(resp.get("clinical_stage") or prompt.get("clinical_stage") or "")

    talk_ok = bool(talk_id) and ("::unknown::" not in talk_id)
    if talk_ok and talk_id not in a_ids and talk_id not in joined_ids:
        talk_ok = "::" in talk_id and not talk_id.endswith("::unknown::1")

    moa_len = len(str(moa).strip())
    findings_n = sum(1 for f in findings if nonempty_text(f))
    has_entity_token = bool(
        re.search(
            r"\b(PD-1|PD-L1|CTLA-4|KRAS|EGFR|HER2|CAR-?T|ADC|VEGF|PARP|CDK\d|BCL-?\d|MET|ALK|RET|ROS1|TIGIT|LAG-?3)\b",
            str(moa) + " " + " ".join(str(f) for f in findings),
            flags=re.I,
        )
    )

    gates = {
        "parse_complete": all(k in resp for k in EXPECTED_SFT_KEYS),
        "moa_present": moa_len >= 40,
        "moa_substantive": moa_len >= 180,
        "findings_present": findings_n >= 1,
        "findings_rich": findings_n >= 3,
        "talk_id_resolvable": talk_ok,
        "entity_anchor": nonempty_text(tumors)
        or (nonempty_text(affiliation) and affiliation.lower() != "unknown")
        or has_entity_token,
        "speaker_known": nonempty_text(speaker) and speaker.lower() != "unknown",
        "stage_specified": nonempty_text(stage)
        and stage.lower() not in {"unspecified", "unknown", "n/a"},
        "evidence_quote": has_evidence_quote(str(moa))
        or any(has_evidence_quote(str(f)) for f in findings),
    }

    weights = {
        "parse_complete": 0.10,
        "moa_present": 0.15,
        "moa_substantive": 0.10,
        "findings_present": 0.15,
        "findings_rich": 0.10,
        "talk_id_resolvable": 0.15,
        "entity_anchor": 0.10,
        "speaker_known": 0.05,
        "stage_specified": 0.05,
        "evidence_quote": 0.05,
    }
    score = sum(weights[k] for k, ok in gates.items() if ok)
    score = round(min(1.0, max(0.0, score)), 4)
    return score, gates


def mutate_wrong_talk_id(chosen: dict, rng: random.Random) -> dict:
    bad = copy.deepcopy(chosen)
    stamp = f"WRONG_TALK_ID::{rng.randint(1000, 9999)}"
    opps = bad.get("crispro_opportunity") or []
    if isinstance(opps, list) and opps and isinstance(opps[0], dict):
        opps[0]["description"] = f"[{stamp}] " + str(opps[0].get("description") or "")
        opps[0]["talk_id_ref"] = stamp
    else:
        bad["wrong_talk_id"] = stamp
    bad["failure_mode"] = "wrong_talk_id"
    return bad


def mutate_missing_quote(chosen: dict) -> dict:
    bad = copy.deepcopy(chosen)
    opps = bad.get("crispro_opportunity") or []
    if isinstance(opps, list):
        for opp in opps:
            if isinstance(opp, dict):
                opp["transcript_evidence"] = ""
                opp.pop("quote", None)
    cd = bad.get("cognitive_dissonance")
    if isinstance(cd, list):
        bad["cognitive_dissonance"] = [
            re.sub(r'"[^"]*"', "", c).strip() if isinstance(c, str) else c for c in cd
        ]
    bad["failure_mode"] = "missing_quote"
    return bad


def mutate_hallucinated_opp(chosen: dict, rng: random.Random) -> dict:
    bad = copy.deepcopy(chosen)
    fake = {
        "opportunity_type": "hallucinated_competitive_whitespace",
        "description": (
            "CrisPRO should acquire the fictional pan-RAS glue degrader ZX-9999 "
            "which the speaker never mentioned, based on an invented 92% ORR in MSS CRC."
        ),
        "transcript_evidence": 'Speaker said: "ZX-9999 cured every patient overnight."',
        "crispro_angle": "Fabricated asset with no transcript support — failure-mode reject.",
        "external_validation_needed": ["None — synthetic hallucination"],
        "priority": "high",
        "hallucinated": True,
    }
    opps = list(bad.get("crispro_opportunity") or [])
    if opps and rng.random() < 0.5:
        opps[0] = fake
    else:
        opps = [fake] + opps
    bad["crispro_opportunity"] = opps
    bad["failure_mode"] = "hallucinated_opp"
    return bad


def mutate_empty_arrays(chosen: dict) -> dict:
    bad = copy.deepcopy(chosen)
    bad["cognitive_dissonance"] = []
    bad["crispro_opportunity"] = []
    bad["vulnerability_identified"] = []
    bad["failure_mode"] = "empty_arrays_on_rich_talk"
    bad["note"] = "Rejected: emptied intel arrays despite rich source talk"
    return bad


def is_rich_chosen(chosen: dict) -> bool:
    opps = chosen.get("crispro_opportunity") or []
    cd = chosen.get("cognitive_dissonance") or []
    vulns = chosen.get("vulnerability_identified") or []
    n = (len(opps) if isinstance(opps, list) else 0) + (
        len(cd) if isinstance(cd, list) else 0
    ) + (len(vulns) if isinstance(vulns, list) else 0)
    has_quote = False
    if isinstance(opps, list):
        for o in opps:
            if isinstance(o, dict) and has_evidence_quote(str(o.get("transcript_evidence") or "")):
                has_quote = True
    return n >= 2 or (n >= 1 and has_quote)


def regenerate_reject(chosen: dict, idx: int, rng: random.Random) -> dict:
    mode = FAILURE_MODES[idx % len(FAILURE_MODES)]
    if mode == "empty_arrays_on_rich_talk" and not is_rich_chosen(chosen):
        mode = FAILURE_MODES[idx % 3]

    if mode == "hallucinated_opp":
        return mutate_hallucinated_opp(chosen, rng)
    if mode == "missing_quote":
        return mutate_missing_quote(chosen)
    if mode == "wrong_talk_id":
        return mutate_wrong_talk_id(chosen, rng)
    return mutate_empty_arrays(chosen)


def rescore_flywheel(
    src: dict,
    *,
    a_ids: set[str],
    joined_ids: set[str],
    seed: int = 2026,
) -> tuple[dict, dict]:
    """Return (scored_payload, stats_dict)."""
    rng = random.Random(seed)
    sft_out = []
    gate_counts = Counter()
    score_hist = Counter()
    for row in src["sft_rows"]:
        new = dict(row)
        score, gates = score_sft_row(new, a_ids, joined_ids)
        new["quality_score"] = score
        new["quality_gates"] = gates
        sft_out.append(new)
        for k, ok in gates.items():
            if ok:
                gate_counts[k] += 1
        score_hist[f"{score:.2f}"] += 1

    pref_out = []
    reject_modes = Counter()
    for i, row in enumerate(src["pref_rows"]):
        new = dict(row)
        chosen = parse_json_field(row.get("chosen_response_json"))
        rejected = regenerate_reject(chosen, i, rng)
        mode = rejected.get("failure_mode", "unknown")
        reject_modes[mode] += 1
        new["rejected_response_json"] = dumps(rejected)
        if not isinstance(new.get("chosen_response_json"), str):
            new["chosen_response_json"] = dumps(chosen)
        new["preference_source"] = "synthetic_failure_mode"
        new["reject_failure_mode"] = mode
        pref_out.append(new)

    out = {
        "sft_rows": sft_out,
        "pref_rows": pref_out,
        "meta": {
            **(src.get("meta") or {}),
            "quality_rescoring": {
                "method": "gate_weights_v1",
                "reject_regeneration": "synthetic_failure_modes_v1",
                "sft_count": len(sft_out),
                "pref_count": len(pref_out),
                "constant_0_85_removed": True,
            },
        },
    }
    stats = {
        "scores": [r["quality_score"] for r in sft_out],
        "gate_counts": gate_counts,
        "score_hist": score_hist,
        "reject_modes": reject_modes,
        "pref_count": len(pref_out),
    }
    return out, stats
