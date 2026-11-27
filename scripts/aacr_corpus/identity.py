"""Name/title similarity helpers, talk_id rewrite, and A↔B cascade join."""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from .schema_b_clean import (
    a_affiliation,
    a_speaker_name,
    b_institution,
    b_speaker_name,
    b_talk_title,
)

WEAK_LAST = frozenset(
    {
        "unknown",
        "speaker",
        "lastname",
        "moderator",
        "chair",
        "panelist",
        "presenter",
        "panel",
    }
)


def last_name(name: str | None) -> str:
    if not name:
        return "unknown"
    n = re.sub(r"\b(MD|PhD|Dr|Professor|Prof|Ms|Mr|Mrs)\b\.?", "", name, flags=re.I)
    n = re.sub(r"[^A-Za-z\-\s]", " ", n)
    parts = [p for p in n.strip().split() if len(p) > 1]
    for p in reversed(parts):
        if p.lower() not in WEAK_LAST and not p.lower().startswith("speaker"):
            return p.lower()
    return parts[-1].lower() if parts else "unknown"


def first_name(name: str | None) -> str:
    if not name:
        return ""
    n = re.sub(r"\b(MD|PhD|Dr|Professor|Prof|Ms|Mr|Mrs)\b\.?", "", name, flags=re.I)
    n = re.sub(r"[^A-Za-z\-\s]", " ", n)
    parts = [p for p in n.strip().split() if len(p) > 1]
    return parts[0].lower() if parts else ""


def name_tokens(name: str | None) -> list[str]:
    if not name:
        return []
    n = re.sub(r"\b(MD|PhD|Dr|Professor|Prof|Ms|Mr|Mrs)\b\.?", "", name, flags=re.I)
    n = re.sub(r"[^A-Za-z\-\s]", " ", n)
    return [p.lower() for p in n.strip().split() if len(p) > 1]


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())).strip()


def sim(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def token_overlap(a: str | None, b: str | None) -> float:
    ta = set(norm(a).split())
    tb = set(norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def title_score(a_title: str | None, b_title: str | None) -> float:
    return max(sim(a_title, b_title), token_overlap(a_title, b_title) * 0.95)


def is_weak_last(ln: str) -> bool:
    return (
        not ln
        or ln in WEAK_LAST
        or ln.startswith("speaker")
        or ln.startswith("lastname")
        or len(ln) <= 2
    )


def name_soft_score(a_name: str, b_name: str) -> float:
    """Soft person match: full sim, first-name, last-name containment / ASR fuzz."""
    if not a_name or not b_name:
        return 0.0
    score = sim(a_name, b_name)
    af, bf = first_name(a_name), first_name(b_name)
    al, bl = last_name(a_name), last_name(b_name)
    if af and af == bf:
        score = max(score, 0.55)
        a_toks = set(name_tokens(a_name))
        b_toks = set(name_tokens(b_name))
        if al in b_toks or bl in a_toks:
            score = max(score, 0.82)
        if not is_weak_last(al) and not is_weak_last(bl) and sim(al, bl) >= 0.8:
            score = max(score, 0.88)
    if not is_weak_last(al) and not is_weak_last(bl):
        score = max(score, sim(al, bl) * 0.95)
    return score


def rewrite_b_talk_id(slug: str, rec: dict, index: int, canonical: str | None) -> str:
    if canonical:
        return canonical
    ln = last_name(b_speaker_name(rec))
    return f"{slug}::{ln}::{index}"


def cascade_join(A: list[dict], B: list[dict]) -> list[tuple[int | None, str]]:
    """Return per-B-record (a_index_or_None, method)."""
    used: set[int] = set()
    by_ln: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(A):
        by_ln[last_name(a_speaker_name(a))].append(i)

    results: list[tuple[int | None, str]] = [(None, "unmatched")] * len(B)
    pending_b: list[int] = []

    for bi, b in enumerate(B):
        name = b_speaker_name(b)
        ln = last_name(name)
        fn = first_name(name)
        title = b_talk_title(b)
        inst = b_institution(b)
        ai = None
        method = "unmatched"

        cands = [i for i in by_ln.get(ln, []) if i not in used]
        if not cands and not is_weak_last(ln):
            for k, idxs in by_ln.items():
                if is_weak_last(k):
                    continue
                if sim(k, ln) >= 0.72 or (
                    len(k) >= 4
                    and len(ln) >= 4
                    and (k.startswith(ln[:4]) or ln.startswith(k[:4]))
                ):
                    cands = [i for i in idxs if i not in used]
                    if cands:
                        break

        if not cands and fn:
            soft = []
            for i, a in enumerate(A):
                if i in used:
                    continue
                an = a_speaker_name(a)
                if first_name(an) == fn and name_soft_score(an, name) >= 0.55:
                    soft.append(i)
            if soft:
                cands = soft
                method = "first_name"

        if len(cands) == 1:
            ai = cands[0]
            method = method if method != "unmatched" else "name"
        elif len(cands) > 1:
            scored = []
            for i in cands:
                a = A[i]
                tscore = title_score(a.get("talk_title"), title)
                ascore = sim(a_affiliation(a), inst)
                nscore = name_soft_score(a_speaker_name(a), name)
                scored.append((tscore + 0.15 * ascore + 0.1 * nscore, i))
            scored.sort(reverse=True)
            if scored[0][0] >= 0.28:
                ai = scored[0][1]
                method = "name_title" if method == "unmatched" else method

        if ai is None:
            scored = []
            for i in range(len(A)):
                if i in used:
                    continue
                a = A[i]
                an = a_speaker_name(a)
                tscore = title_score(a.get("talk_title"), title)
                nscore = name_soft_score(an, name)
                ascore = sim(a_affiliation(a), inst)
                combined = 0.55 * tscore + 0.35 * nscore + 0.10 * ascore
                scored.append((combined, tscore, nscore, i))
            scored.sort(reverse=True)
            if scored:
                best, tscore, nscore, idx = scored[0]
                if nscore >= 0.8 and best >= 0.40:
                    ai, method = idx, "asr_name"
                elif tscore >= 0.55 and best >= 0.45:
                    ai, method = idx, "title"
                elif best >= 0.52:
                    ai, method = idx, "title_fuzzy"

        if ai is not None:
            used.add(ai)
            results[bi] = (ai, method)
        else:
            pending_b.append(bi)

    leftover_a = [i for i in range(len(A)) if i not in used]

    if leftover_a and pending_b and len(leftover_a) == len(pending_b):
        for ai, bi in zip(leftover_a, pending_b):
            results[bi] = (ai, "order")
            used.add(ai)
        pending_b = []
        leftover_a = [i for i in range(len(A)) if i not in used]

    if leftover_a and pending_b:
        rem = list(leftover_a)
        still_pending: list[int] = []
        last_ai = -1
        for bi in pending_b:
            b = B[bi]
            name = b_speaker_name(b)
            title = b_talk_title(b)
            inst = b_institution(b)
            best = None
            for j, ai in enumerate(rem):
                a = A[ai]
                tscore = title_score(a.get("talk_title"), title)
                nscore = name_soft_score(a_speaker_name(a), name)
                ascore = sim(a_affiliation(a), inst)
                score = 0.5 * tscore + 0.4 * nscore + 0.1 * ascore
                if ai > last_ai:
                    score += 0.03
                if score >= 0.38 and (best is None or score > best[0]):
                    best = (score, j, ai)
            if best and best[0] >= 0.42:
                _, j, ai = best
                results[bi] = (ai, "shift_align")
                used.add(ai)
                last_ai = ai
                rem.pop(j)
            else:
                still_pending.append(bi)
        pending_b = still_pending

    return results
