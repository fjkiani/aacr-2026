#!/usr/bin/env python3
"""
AACR 2026 Full Extraction Pipeline v6
Anti-reap: heartbeat thread touches disk every 5 min
Real-time Schema B hit logger for cognitive dissonance + resistance
Primary: openai/gpt-oss-120b:free  Fallback: google/gemma-4-31b-it:free
"""
import requests, json, time, re, os, csv, sys, threading
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
KEYS = [
    os.environ.get("OPENROUTER_KEY_1", ""),
    os.environ.get("OPENROUTER_KEY_2", ""),
]
MODELS = [
    "openai/gpt-oss-120b:free",
    "google/gemma-4-31b-it:free",
]
MAX_TOKENS  = 8000
TEMPERATURE = 0.1
CALL_SLEEP  = 10
MAX_RETRIES = 6

TRANSCRIPTS_DIR = Path("/mnt/results/aacr2026/transcripts")
SCHEMAS_DIR     = Path("/mnt/results/aacr2026/schemas")
OUT_DIR_A       = Path("/mnt/results/aacr2026/extractions/schema_a")
OUT_DIR_B       = Path("/mnt/results/aacr2026/extractions/schema_b")
RUN_LOG         = Path("/mnt/shared-workspace/run_log_v6.jsonl")
HEARTBEAT_FILE  = Path("/mnt/shared-workspace/heartbeat.txt")
HIT_LOG         = Path("/mnt/shared-workspace/schema_b_hits.jsonl")

OUT_DIR_A.mkdir(parents=True, exist_ok=True)
OUT_DIR_B.mkdir(parents=True, exist_ok=True)

# ── Anti-reap heartbeat ───────────────────────────────────────────────────────
def heartbeat_loop():
    """Touch disk every 5 minutes to prevent inactivity termination."""
    while True:
        try:
            HEARTBEAT_FILE.write_text(f"alive {datetime.now().isoformat()}")
        except: pass
        time.sleep(300)

hb = threading.Thread(target=heartbeat_loop, daemon=True)
hb.start()
print(f"[{datetime.now().strftime('%H:%M:%S')}] Heartbeat thread started.")

# ── Key/model rotation ────────────────────────────────────────────────────────
_key_idx   = 0
_model_idx = 0
_key_cooldown = {}

def get_headers():
    global _key_idx
    now = time.time()
    for _ in range(len(KEYS)):
        if _key_cooldown.get(_key_idx, 0) <= now:
            break
        _key_idx = (_key_idx + 1) % len(KEYS)
    return {"Authorization": f"Bearer {KEYS[_key_idx]}", "Content-Type": "application/json",
            "HTTP-Referer": "https://biomni.phylo.com", "X-Title": "AACR2026"}, _key_idx

def rotate_key(key_idx, cooldown=70):
    global _key_idx
    _key_cooldown[key_idx] = time.time() + cooldown
    _key_idx = (_key_idx + 1) % len(KEYS)
    print(f"    Key {key_idx} cooling {cooldown}s → key {_key_idx}")

def rotate_model():
    global _model_idx
    _model_idx = (_model_idx + 1) % len(MODELS)
    print(f"    Model → {MODELS[_model_idx].split('/')[-1]}")

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

# ── Real-time Schema B hit printer ────────────────────────────────────────────
def print_b_hits(records, slug, title):
    """Print cognitive dissonance and unexplained resistance hits as they land."""
    for rec in records:
        meta = rec.get("talk_metadata", {})
        speaker = meta.get("speaker_name", "?")

        cd = rec.get("cognitive_dissonance", [])
        vulns = rec.get("vulnerability_identified", [])
        resist = [v for v in vulns if v.get("unexplained_resistance_quote")]

        if cd or resist:
            print(f"\n  ╔══ SCHEMA B HIT ══════════════════════════════════════════")
            print(f"  ║ Speaker: {speaker}")
            print(f"  ║ Session: {title[:60]}")
            for c in cd:
                print(f"  ║ [COGNITIVE DISSONANCE] {c[:200]}")
            for v in resist:
                print(f"  ║ [UNEXPLAINED RESISTANCE] {v.get('failing_compound_or_target','?')}: {v.get('unexplained_resistance_quote','')[:150]}")
            print(f"  ╚══════════════════════════════════════════════════════════")

            # Log to hit file
            hit = {
                "ts": datetime.now().isoformat(),
                "slug": slug, "speaker": speaker,
                "cognitive_dissonance": cd,
                "unexplained_resistance": [v.get("unexplained_resistance_quote","") for v in resist if v.get("unexplained_resistance_quote")],
            }
            try:
                with open(HIT_LOG, "a") as f:
                    f.write(json.dumps(hit) + "\n")
            except: pass

# ── API call ──────────────────────────────────────────────────────────────────
def call_model(system_prompt, user_prompt):
    global _model_idx
    for attempt in range(MAX_RETRIES):
        headers, key_idx = get_headers()
        model = MODELS[_model_idx]
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={"model": model,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user",   "content": user_prompt}],
                      "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE},
                timeout=360,
            )
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"], data.get("usage", {}), model
            elif r.status_code == 429:
                m = re.search(r'(\d+)s', r.text)
                delay = int(m.group(1)) + 10 if m else 70
                print(f"    429 key={key_idx} {model.split('/')[-1]} attempt={attempt+1} wait={delay}s")
                rotate_key(key_idx, delay)
                if attempt % 2 == 1: rotate_model()
                time.sleep(min(delay, 80))
            elif r.status_code in (500, 503):
                wait = 30 * (attempt + 1)
                print(f"    {r.status_code} {model.split('/')[-1]} attempt={attempt+1} wait={wait}s")
                rotate_model()
                time.sleep(wait)
            else:
                print(f"    HTTP {r.status_code}: {r.text[:150]}")
                time.sleep(20)
        except requests.exceptions.Timeout:
            print(f"    Timeout attempt={attempt+1}")
            time.sleep(20)
        except Exception as e:
            print(f"    Exception: {e}")
            time.sleep(20)
    return None, {}, model

# ── Extract one session ───────────────────────────────────────────────────────
def extract_session(slug, title, schema_label, system_prompt, out_dir, chunk=False):
    transcript = open(TRANSCRIPTS_DIR / f"{slug}.txt").read()
    if chunk:
        mid = len(transcript) // 2
        sp = transcript.rfind('. ', mid-2000, mid+2000)
        sp = (sp + 2) if sp != -1 else mid
        parts = [(transcript[:sp], "P1"), (transcript[sp:], "P2")]
    else:
        parts = [(transcript, "")]

    all_records = []
    for part_text, part_label in parts:
        lbl = f"({part_label})" if part_label else ""
        user_prompt = f"""SESSION TITLE: {title} {lbl}
SESSION SLUG: {slug}

TRANSCRIPT {lbl}:
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
                print(f"    {schema_label}{lbl}: ❌ parse_failed | out={usage.get('completion_tokens',0)}")
                return None, "parse_failed"
        else:
            print(f"    {schema_label}{lbl}: ❌ api_error")
            return None, "api_error"

        if part_label == "P1":
            time.sleep(CALL_SLEEP)

    for i, rec in enumerate(all_records):
        last = rec.get("speaker", {}).get("name", "unknown").split()[-1].lower()
        rec["talk_id"] = f"{slug}::{last}::{i+1}"

    with open(out_dir / f"{slug}.json", "w") as f:
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
done_a = {p.stem for p in OUT_DIR_A.glob("*.json") if "_raw" not in p.stem}
done_b = {p.stem for p in OUT_DIR_B.glob("*.json") if "_raw" not in p.stem}
remaining = sum(1 for s, _ in sessions if s not in done_a or s not in done_b)
print(f"[{datetime.now().strftime('%H:%M:%S')}] Total={total} | DoneA={len(done_a)} | DoneB={len(done_b)} | Remaining={remaining}")
print(f"[{datetime.now().strftime('%H:%M:%S')}] Launching. Blood spatter will print in real-time.\n")

# ── Main loop ─────────────────────────────────────────────────────────────────
for idx, (slug, title) in enumerate(sessions):
    need_a = slug not in done_a
    need_b = slug not in done_b
    if not need_a and not need_b:
        continue

    ts = datetime.now().strftime('%H:%M:%S')
    da = len(list(OUT_DIR_A.glob("*.json")))
    db = len(list(OUT_DIR_B.glob("*.json")))
    print(f"[{ts}] [{da}A/{db}B/{total}] {title[:65]}")
    result = {"slug": slug, "ts": datetime.now().isoformat()}

    if need_a:
        recs_a, st_a = extract_session(slug, title, "A", SYSTEM_A, OUT_DIR_A)
        result["a_status"] = st_a
        result["a_n"] = len(recs_a) if recs_a else 0
        tx_len = os.path.getsize(TRANSCRIPTS_DIR / f"{slug}.txt")
        if recs_a is not None and tx_len > 85000 and len(recs_a) < 3:
            print(f"    ⚠ Truncation ({len(recs_a)} spk, {tx_len:,}c) — chunking")
            time.sleep(CALL_SLEEP)
            recs_a2, st_a2 = extract_session(slug, title, "A-chunk", SYSTEM_A, OUT_DIR_A, chunk=True)
            if recs_a2 and len(recs_a2) > len(recs_a):
                result["a_status"] = "ok_chunked"; result["a_n"] = len(recs_a2)
        time.sleep(CALL_SLEEP)

    if need_b:
        recs_b, st_b = extract_session(slug, title, "B", SYSTEM_B, OUT_DIR_B)
        result["b_status"] = st_b
        result["b_n"] = len(recs_b) if recs_b else 0
        if recs_b:
            print_b_hits(recs_b, slug, title)
        time.sleep(CALL_SLEEP)

    try:
        with open(RUN_LOG, "a") as f:
            f.write(json.dumps(result) + "\n")
    except Exception as e:
        print(f"    Log error: {e}")

    if (idx + 1) % 10 == 0:
        da = len(list(OUT_DIR_A.glob("*.json")))
        db = len(list(OUT_DIR_B.glob("*.json")))
        print(f"\n  ═══ [{datetime.now().strftime('%H:%M:%S')}] A={da}/{total}  B={db}/{total} ═══\n")

print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✅ COMPLETE")
print(f"A={len(list(OUT_DIR_A.glob('*.json')))}  B={len(list(OUT_DIR_B.glob('*.json')))}")
