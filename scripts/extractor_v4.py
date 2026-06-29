#!/usr/bin/env python3
"""
AACR 2026 Full Extraction Pipeline v4
Models: gemma-4-31b-it (primary), gemma-4-26b-a4b-it (secondary)
API: OpenRouter with dual-key rotation
"""
import requests, json, time, re, os, csv, sys
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
KEYS = [
    os.environ.get("OPENROUTER_KEY_1", ""),
    os.environ.get("OPENROUTER_KEY_2", ""),
]
MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]
MAX_TOKENS   = 8000
TEMPERATURE  = 0.1
CALL_SLEEP   = 8    # seconds between calls
MAX_RETRIES  = 6

TRANSCRIPTS_DIR = Path("/mnt/results/aacr2026/transcripts")
SCHEMAS_DIR     = Path("/mnt/results/aacr2026/schemas")
OUT_DIR         = Path("/mnt/results/aacr2026/extractions")
OUT_DIR_A       = OUT_DIR / "schema_a"
OUT_DIR_B       = OUT_DIR / "schema_b"
RUN_LOG         = OUT_DIR / "run_log_v4.jsonl"

OUT_DIR_A.mkdir(parents=True, exist_ok=True)
OUT_DIR_B.mkdir(parents=True, exist_ok=True)

# ── Key rotation state ────────────────────────────────────────────────────────
_key_idx   = 0
_model_idx = 0
_key_cooldown = {}   # key_idx -> timestamp when it can be used again

def get_headers():
    global _key_idx
    # Find a key not in cooldown
    now = time.time()
    for _ in range(len(KEYS)):
        if _key_cooldown.get(_key_idx, 0) <= now:
            break
        _key_idx = (_key_idx + 1) % len(KEYS)
    return {
        "Authorization": f"Bearer {KEYS[_key_idx]}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://biomni.phylo.com",
        "X-Title": "AACR2026",
    }, _key_idx

def rotate_key(key_idx, cooldown_secs=65):
    global _key_idx
    _key_cooldown[key_idx] = time.time() + cooldown_secs
    _key_idx = (_key_idx + 1) % len(KEYS)
    print(f"    Key {key_idx} cooling down {cooldown_secs}s → switching to key {_key_idx}")

def rotate_model():
    global _model_idx
    _model_idx = (_model_idx + 1) % len(MODELS)
    print(f"    Switching to model: {MODELS[_model_idx]}")

# ── Load schemas ──────────────────────────────────────────────────────────────
with open(SCHEMAS_DIR / "schema_a_scientific.json") as f:
    SCHEMA_A_STR = json.dumps(json.load(f), indent=2)
with open(SCHEMAS_DIR / "schema_b_competitive_intel.json") as f:
    SCHEMA_B_STR = json.dumps(json.load(f), indent=2)

SYSTEM_A = f"""You are a precision oncology research analyst extracting structured data from AACR 2026 conference session transcripts.

TASK: Read the full session transcript and produce ONE JSON record per individual speaker who presents original data or a substantive scientific argument. DO NOT create a record for session chairs who only give brief introductory remarks with no primary data. If the session chair also presents data, include them.

OUTPUT FORMAT: A JSON array of records. Output ONLY the JSON array — no prose, no markdown fences, no thinking text. Start your response with [ and end with ].

SCHEMA (ScientificTalkExtraction_v2):
{SCHEMA_A_STR}

RULES:
1. All required fields MUST be present. Arrays use [] when nothing applies.
2. talk_id: "session_slug::speaker_last_name::index" (index starts at 1).
3. key_findings: data-grounded with specific numbers. Include every statistic.
4. clinical_data: Extract EVERY number — ORR, pCR, PFS, OS, HR, p-values, n=.
5. external_follow_up: always include all 5 sub-arrays ([] if nothing mentioned).
6. Do NOT hallucinate. Use [] for empty arrays, "unspecified" for unknown enums."""

SYSTEM_B = f"""You are a precision oncology competitive intelligence analyst extracting structured data from AACR 2026 conference session transcripts.

TASK: Read the full session transcript and produce ONE JSON record per individual speaker who presents original data or a substantive scientific argument. DO NOT create a record for intro-only session chairs.

OUTPUT FORMAT: A JSON array of records. Output ONLY the JSON array — no prose, no markdown fences. Start with [ and end with ].

SCHEMA (CompetitiveIntelExtraction_v2):
{SCHEMA_B_STR}

RULES:
1. All required fields MUST be present. Arrays use [] when nothing applies.
2. talk_id must match the Schema A talk_id for the same speaker.
3. rhetorical_signals: Direct quotes only — never paraphrase.
4. cognitive_dissonance: Must cite both the observation AND the contradictory conclusion.
5. Do NOT hallucinate. Ground everything in the transcript."""

# ── JSON extraction ───────────────────────────────────────────────────────────
def extract_json_robust(text):
    if not text: return None
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    start = text.find('[')
    if start == -1:
        s = text.find('{')
        if s != -1: text = '[' + text[s:]
        else: return None
    else:
        text = text[start:]
    end = text.rfind(']')
    if end != -1:
        candidate = re.sub(r',\s*([}\]])', r'\1', text[:end+1])
        try: return json.loads(candidate)
        except: pass
    # Repair truncated: extract complete objects
    records, depth, obj_start, i = [], 0, None, 0
    while i < len(text):
        c = text[i]
        if c == '{' and depth == 0: obj_start = i; depth = 1
        elif c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try: records.append(json.loads(re.sub(r',\s*([}\]])', r'\1', text[obj_start:i+1])))
                except: pass
                obj_start = None
        elif c == '"' and depth > 0:
            i += 1
            while i < len(text) and text[i] != '"':
                if text[i] == '\\': i += 1
                i += 1
        i += 1
    return records if records else None

# ── API call with key rotation + model fallback ───────────────────────────────
def call_model(system_prompt, user_prompt):
    global _model_idx
    for attempt in range(MAX_RETRIES):
        headers, key_idx = get_headers()
        model = MODELS[_model_idx]
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "max_tokens": MAX_TOKENS,
                    "temperature": TEMPERATURE,
                },
                timeout=360,
            )
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return content, usage, model
            elif r.status_code == 429:
                # Extract retry-after if present
                body = r.text
                delay_match = re.search(r'retry.*?(\d+)', body, re.I)
                delay = int(delay_match.group(1)) + 5 if delay_match else 65
                print(f"    429 key={key_idx} model={model.split('/')[-1]} attempt={attempt+1} — rotating key, wait {delay}s")
                rotate_key(key_idx, delay)
                if attempt % 2 == 1:
                    rotate_model()
                time.sleep(min(delay, 70))
            elif r.status_code in (500, 503):
                wait = 30 * (attempt + 1)
                print(f"    {r.status_code} model={model.split('/')[-1]} attempt={attempt+1} — wait {wait}s")
                rotate_model()
                time.sleep(wait)
            else:
                print(f"    HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(20)
        except requests.exceptions.Timeout:
            print(f"    Timeout attempt={attempt+1} — retrying")
            time.sleep(20)
        except Exception as e:
            print(f"    Exception: {e}")
            time.sleep(20)
    return None, {}, model

# ── Extract one session (with optional chunking) ──────────────────────────────
def extract_session(slug, title, schema_label, system_prompt, out_dir, chunk=False):
    transcript = open(TRANSCRIPTS_DIR / f"{slug}.txt").read()
    if chunk:
        mid = len(transcript) // 2
        sp = transcript.rfind('. ', mid-2000, mid+2000)
        sp = (sp + 2) if sp != -1 else mid
        parts = [(transcript[:sp], "Part1"), (transcript[sp:], "Part2")]
    else:
        parts = [(transcript, "")]

    all_records = []
    for part_text, part_label in parts:
        lbl = f" ({part_label})" if part_label else ""
        user_prompt = f"""SESSION TITLE: {title}{lbl}
SESSION SLUG: {slug}

TRANSCRIPT{lbl}:
{part_text}

Extract one JSON record per data-presenting speaker{" in THIS PART" if part_label else ""}. Output a JSON array starting with [."""

        t0 = time.time()
        content, usage, used_model = call_model(system_prompt, user_prompt)
        elapsed = time.time() - t0

        if content:
            records = extract_json_robust(content)
            if records:
                all_records.extend(records)
                print(f"    {schema_label}{lbl}: ✅ {elapsed:.0f}s | {len(records)} spk | {used_model.split('/')[-1]} | out={usage.get('completion_tokens',0)}")
            else:
                print(f"    {schema_label}{lbl}: ❌ parse_failed | out={usage.get('completion_tokens',0)} | raw={len(content)}c")
                return None, "parse_failed"
        else:
            print(f"    {schema_label}{lbl}: ❌ api_error")
            return None, "api_error"

        if part_label == "Part1":
            time.sleep(CALL_SLEEP)

    # Reindex talk_ids
    for i, rec in enumerate(all_records):
        last = rec.get("speaker", {}).get("name", "unknown").split()[-1].lower()
        rec["talk_id"] = f"{slug}::{last}::{i+1}"

    out_path = out_dir / f"{slug}.json"
    with open(out_path, "w") as f:
        json.dump(all_records, f, indent=2)
    return all_records, "ok"

# ── Load sessions ─────────────────────────────────────────────────────────────
sessions = []
with open("/mnt/results/aacr2026/sessions.csv") as f:
    for row in csv.DictReader(f):
        slug = row.get("slug", "")
        if (TRANSCRIPTS_DIR / f"{slug}.txt").exists():
            sessions.append((slug, row.get("title", slug)))

total = len(sessions)
done_a = {p.stem for p in OUT_DIR_A.glob("*.json")}
done_b = {p.stem for p in OUT_DIR_B.glob("*.json")}
remaining = [(s, t) for s, t in sessions if s not in done_a or s not in done_b]
print(f"Total: {total} | Done A: {len(done_a)} | Done B: {len(done_b)} | Remaining: {len(remaining)}")

# ── Main loop ─────────────────────────────────────────────────────────────────
for idx, (slug, title) in enumerate(sessions):
    need_a = slug not in done_a
    need_b = slug not in done_b
    if not need_a and not need_b:
        continue

    print(f"\n[{idx+1}/{total}] {title[:65]}")
    result = {"slug": slug, "title": title, "ts": datetime.now().isoformat()}

    if need_a:
        recs_a, st_a = extract_session(slug, title, "A", SYSTEM_A, OUT_DIR_A)
        result["a_status"] = st_a
        result["a_n"] = len(recs_a) if recs_a else 0
        # Auto-chunk if suspiciously few speakers on long transcript
        tx_len = os.path.getsize(TRANSCRIPTS_DIR / f"{slug}.txt")
        if recs_a is not None and tx_len > 90000 and len(recs_a) < 3:
            print(f"    ⚠ Truncation suspected ({len(recs_a)} spk, {tx_len:,}c) — chunking")
            time.sleep(CALL_SLEEP)
            recs_a2, st_a2 = extract_session(slug, title, "A-chunked", SYSTEM_A, OUT_DIR_A, chunk=True)
            if recs_a2 and len(recs_a2) > len(recs_a):
                result["a_status"] = st_a2 + "_chunked"
                result["a_n"] = len(recs_a2)
        time.sleep(CALL_SLEEP)

    if need_b:
        recs_b, st_b = extract_session(slug, title, "B", SYSTEM_B, OUT_DIR_B)
        result["b_status"] = st_b
        result["b_n"] = len(recs_b) if recs_b else 0
        time.sleep(CALL_SLEEP)

    with open(RUN_LOG, "a") as f:
        f.write(json.dumps(result) + "\n")

    if (idx + 1) % 10 == 0:
        da = len(list(OUT_DIR_A.glob("*.json")))
        db = len(list(OUT_DIR_B.glob("*.json")))
        print(f"\n  ═══ Progress: A={da}/{total}  B={db}/{total} ═══\n")

print("\n✅ Done!")
print(f"A: {len(list(OUT_DIR_A.glob('*.json')))}  B: {len(list(OUT_DIR_B.glob('*.json')))}")
