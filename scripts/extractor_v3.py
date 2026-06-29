#!/usr/bin/env python3
"""
AACR 2026 Full Extraction Pipeline v3
Primary model: gemini-2.5-flash-lite (Google AI API)
Fallback model: gemini-2.5-flash
Schemas: ScientificTalkExtraction_v2 (A) + CompetitiveIntelExtraction_v2 (B)
"""

import json, time, re, os, sys, csv
from pathlib import Path
from datetime import datetime
from google import genai
from google.genai import types

# ── Config ──────────────────────────────────────────────────────────────────
GEMINI_KEY = "AIzaSyBawXQCm9VYDsyi88Z0Hv0kJdrcNRIF9Uo"
MODEL_PRIMARY  = "models/gemini-2.5-flash-lite"
MODEL_FALLBACK = "models/gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 16384
TEMPERATURE = 0.1
CALL_SLEEP = 6        # seconds between calls (conservative)
RETRY_SLEEP_BASE = 20 # base seconds for backoff
MAX_RETRIES = 4

TRANSCRIPTS_DIR = Path("/mnt/results/aacr2026/transcripts")
SCHEMAS_DIR     = Path("/mnt/results/aacr2026/schemas")
OUT_DIR         = Path("/mnt/results/aacr2026/extractions")
OUT_DIR_A       = OUT_DIR / "schema_a"
OUT_DIR_B       = OUT_DIR / "schema_b"
RUN_LOG         = OUT_DIR / "run_log_v3.jsonl"

OUT_DIR_A.mkdir(parents=True, exist_ok=True)
OUT_DIR_B.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=GEMINI_KEY)

# ── Load schemas ─────────────────────────────────────────────────────────────
with open(SCHEMAS_DIR / "schema_a_scientific.json") as f:
    SCHEMA_A_STR = json.dumps(json.load(f), indent=2)
with open(SCHEMAS_DIR / "schema_b_competitive_intel.json") as f:
    SCHEMA_B_STR = json.dumps(json.load(f), indent=2)

# ── System prompts ────────────────────────────────────────────────────────────
SYSTEM_A = f"""You are a precision oncology research analyst extracting structured data from AACR 2026 conference session transcripts.

TASK: Read the full session transcript and produce ONE JSON record per individual speaker who presents original data or a substantive scientific argument. DO NOT create a record for session chairs who only give brief introductory remarks with no primary data. If the session chair also presents data (common at AACR), include them.

OUTPUT FORMAT: A JSON array of records. Output ONLY the JSON array — no prose, no markdown fences, no thinking text. Start your response with [ and end with ].

SCHEMA (ScientificTalkExtraction_v2) — every record must conform to this:
{SCHEMA_A_STR}

EXTRACTION RULES:
1. All required fields MUST be present. Array fields use [] when nothing applies.
2. talk_id: "session_slug::speaker_last_name::index" — index starts at 1.
3. talk_title: Always fill. Construct from content if not stated.
4. key_findings: Specific, data-grounded with numbers. Include every statistic.
5. MOA_summary: 2-4 sentences, mechanistically specific.
6. clinical_data: Extract EVERY number — ORR, pCR, PFS, OS, HR, p-values, n=, response rates.
7. external_follow_up: Always include with all 5 sub-arrays ([] if nothing mentioned).
8. Do NOT hallucinate. Use [] for empty arrays, "unspecified" for enums when unclear."""

SYSTEM_B = f"""You are a precision oncology competitive intelligence analyst extracting structured data from AACR 2026 conference session transcripts.

TASK: Read the full session transcript and produce ONE JSON record per individual speaker who presents original data or a substantive scientific argument. DO NOT create a record for session chairs who only give brief introductory remarks with no primary data.

OUTPUT FORMAT: A JSON array of records. Output ONLY the JSON array — no prose, no markdown fences. Start your response with [ and end with ].

SCHEMA (CompetitiveIntelExtraction_v2) — every record must conform to this:
{SCHEMA_B_STR}

EXTRACTION RULES:
1. All required fields MUST be present. Array fields use [] when nothing applies.
2. talk_id must match the Schema A talk_id for the same speaker.
3. rhetorical_signals: Direct quotes only — never paraphrase or label.
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

# ── API call with retry + model fallback ─────────────────────────────────────
def call_gemini(system_prompt, user_prompt, max_tokens=MAX_OUTPUT_TOKENS):
    combined = f"{system_prompt}\n\n{user_prompt}"
    for attempt in range(MAX_RETRIES):
        model = MODEL_PRIMARY if attempt < 2 else MODEL_FALLBACK
        wait = RETRY_SLEEP_BASE * (2 ** attempt)
        try:
            cfg = types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=TEMPERATURE,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )
            response = client.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=[types.Part(text=combined)])],
                config=cfg,
            )
            text = response.text or ""
            usage = response.usage_metadata
            return text, {
                "model": model,
                "prompt_tokens": usage.prompt_token_count if usage else 0,
                "output_tokens": usage.candidates_token_count if usage else 0,
            }
        except Exception as e:
            err = str(e)
            if "503" in err or "UNAVAILABLE" in err:
                print(f"    503 overload (attempt {attempt+1}/{MAX_RETRIES}) — waiting {wait}s, trying {MODEL_FALLBACK if attempt >= 1 else MODEL_PRIMARY}")
                time.sleep(wait)
            elif "429" in err or "RESOURCE_EXHAUSTED" in err:
                # Extract retry delay from error if available
                import re as _re
                delay_match = _re.search(r'retryDelay.*?(\d+)s', err)
                delay = int(delay_match.group(1)) + 5 if delay_match else wait
                print(f"    429 rate limit (attempt {attempt+1}/{MAX_RETRIES}) — waiting {delay}s")
                time.sleep(delay)
            elif "500" in err or "INTERNAL" in err:
                print(f"    500 internal error (attempt {attempt+1}/{MAX_RETRIES}) — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"    Unexpected error: {err[:200]}")
                if attempt < MAX_RETRIES - 1: time.sleep(wait)
                else: raise
    return None, {}

# ── Extract one session ───────────────────────────────────────────────────────
def extract_session(slug, title, schema_label, system_prompt, out_dir, chunk=False):
    transcript = open(TRANSCRIPTS_DIR / f"{slug}.txt").read()

    if chunk:
        mid = len(transcript) // 2
        sp = transcript.rfind('. ', mid-2000, mid+2000)
        if sp == -1: sp = mid
        sp += 2
        parts = [(transcript[:sp], "Part 1"), (transcript[sp:], "Part 2")]
    else:
        parts = [(transcript, "")]

    all_records = []
    for part_text, part_label in parts:
        label_str = f" ({part_label})" if part_label else ""
        user_prompt = f"""SESSION TITLE: {title}{label_str}
SESSION SLUG: {slug}

TRANSCRIPT{label_str}:
{part_text}

Extract one JSON record per data-presenting speaker{" in THIS PART of the transcript" if part_label else ""}. Output a JSON array starting with [."""

        t0 = time.time()
        text, usage = call_gemini(system_prompt, user_prompt)
        elapsed = time.time() - t0

        if text:
            records = extract_json_robust(text)
            if records:
                all_records.extend(records)
                print(f"    {schema_label}{label_str}: ✅ {elapsed:.1f}s | {len(records)} speakers | model={usage.get('model','?').split('/')[-1]} in={usage.get('prompt_tokens',0)} out={usage.get('output_tokens',0)}")
            else:
                print(f"    {schema_label}{label_str}: ❌ parse_failed | out={usage.get('output_tokens',0)} | raw={len(text)} chars")
                return None, "parse_failed"
        else:
            print(f"    {schema_label}{label_str}: ❌ api_error")
            return None, "api_error"

        if part_label == "Part 1":
            time.sleep(CALL_SLEEP)

    # Fix talk_id indices
    for i, rec in enumerate(all_records):
        last = rec.get("speaker", {}).get("name", "unknown").split()[-1].lower()
        rec["talk_id"] = f"{slug}::{last}::{i+1}"

    out_path = out_dir / f"{slug}.json"
    with open(out_path, "w") as f:
        json.dump(all_records, f, indent=2)

    return all_records, "ok"

# ── Load session list ─────────────────────────────────────────────────────────
sessions = []
with open("/mnt/results/aacr2026/sessions.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        slug = row.get("slug", "")
        if (TRANSCRIPTS_DIR / f"{slug}.txt").exists():
            sessions.append((slug, row.get("title", slug)))

total = len(sessions)
done_a = {p.stem for p in OUT_DIR_A.glob("*.json")}
done_b = {p.stem for p in OUT_DIR_B.glob("*.json")}
print(f"Total sessions: {total} | Done A: {len(done_a)} | Done B: {len(done_b)}")
print(f"Remaining: {total - len(done_a)} Schema A, {total - len(done_b)} Schema B")

# ── Main loop ─────────────────────────────────────────────────────────────────
for idx, (slug, title) in enumerate(sessions):
    need_a = slug not in done_a
    need_b = slug not in done_b
    if not need_a and not need_b:
        continue

    print(f"\n[{idx+1}/{total}] {title[:65]}")
    result = {"slug": slug, "title": title, "timestamp": datetime.now().isoformat()}

    if need_a:
        records_a, status_a = extract_session(slug, title, "Schema A", SYSTEM_A, OUT_DIR_A)
        result["schema_a_status"] = status_a
        result["schema_a_n"] = len(records_a) if records_a else 0

        # Auto-chunk if very few speakers on a long transcript
        if records_a is not None and len(open(TRANSCRIPTS_DIR / f"{slug}.txt").read()) > 90000 and len(records_a) < 3:
            print(f"    ⚠️  Possible truncation ({len(records_a)} speakers on long transcript) — retrying chunked")
            time.sleep(CALL_SLEEP)
            records_a2, status_a2 = extract_session(slug, title, "Schema A (chunked)", SYSTEM_A, OUT_DIR_A, chunk=True)
            if records_a2 and len(records_a2) > len(records_a):
                result["schema_a_status"] = status_a2 + "_chunked"
                result["schema_a_n"] = len(records_a2)

        time.sleep(CALL_SLEEP)

    if need_b:
        records_b, status_b = extract_session(slug, title, "Schema B", SYSTEM_B, OUT_DIR_B)
        result["schema_b_status"] = status_b
        result["schema_b_n"] = len(records_b) if records_b else 0
        time.sleep(CALL_SLEEP)

    with open(RUN_LOG, "a") as f:
        f.write(json.dumps(result) + "\n")

    if (idx + 1) % 10 == 0:
        done_now_a = len(list(OUT_DIR_A.glob("*.json")))
        done_now_b = len(list(OUT_DIR_B.glob("*.json")))
        print(f"\n  === Progress: A={done_now_a}/{total} B={done_now_b}/{total} ===\n")

print("\n✅ Extraction complete!")
print(f"Schema A: {len(list(OUT_DIR_A.glob('*.json')))} sessions")
print(f"Schema B: {len(list(OUT_DIR_B.glob('*.json')))} sessions")
