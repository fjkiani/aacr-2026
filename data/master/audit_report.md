# AACR 2026 Transcript Extraction — Audit Report

**Generated:** 2026-06-11 05:18 UTC  
**Pipeline:** Vimeo event embed → player config → VTT download → plain text  
**Source:** AACR 2026 Annual Meeting (connect.aacr26.org)

---

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 273 |
| Sessions with transcripts | 272 |
| Sessions without transcripts | 1 |
| Success rate | 99.6% |
| Total transcript text | 20,655,689 chars (~20M) |
| Total VTT data | 35,356,764 chars |
| Avg transcript length | 75,940 chars |
| Min transcript length | 27,949 chars |
| Max transcript length | 114,275 chars |

---

## Output Files

| File | Description |
|------|-------------|
| sessions.csv | All 273 sessions with metadata and status |
| sessions.jsonl | Same, newline-delimited JSON |
| failures.jsonl | Sessions without transcripts |
| transcripts/SLUG.vtt | Raw VTT with timestamps (272 files) |
| transcripts/SLUG.txt | Clean plain text (272 files) |
| manifests/SLUG.json | Per-session metadata + Vimeo IDs (272 files) |

---

## Caption Label Breakdown

| Label | Count |
|-------|-------|
| English (auto-generated) | 272 |

---

## Top Session Categories

| Category | Sessions |
|----------|----------|
| Clinical Research | 82 |
| Molecular/Cellular Biology and Genetics | 63 |
| Tumor Biology | 52 |
| Prevention / Early Detection / Interception | 50 |
| Survivorship | 45 |
| Immunology | 35 |
| Drug Development | 34 |
| Chemistry | 29 |
| Bioinformatics / Computational Biology / Artificial Intelligence / Data Science | 28 |
| Population Sciences | 28 |
| Cancer Evolution | 27 |
|  | 24 |
| Tumor Microenvironment | 24 |
| Experimental and Molecular Therapeutics | 24 |
| Clinical Trials | 19 |

---

## Failures (1 session)

| Session | Failure Reason |
|---------|----------------|
| AI-Based Tissue Biomarkers in Cancer: Multimodal AI Across Scales | no_vtt_url |

### Failure Analysis

**AI-Based Tissue Biomarkers in Cancer: Multimodal AI Across Scales** (Vimeo event `5841816`, video `1179383861`):
- Video exists and is 6,178 seconds (~1h 43m) long
- `ai: 0` flag in player config — Vimeo AI caption generation was disabled for this video
- No manually uploaded captions either
- Not a pipeline bug; this session genuinely has no caption track available

---

## Pipeline Architecture

```
For each session (273 total):
  1. Extract Vimeo event ID from AACR GraphQL session detail
  2. GET vimeo.com/event/{event_id}/embed
     -> parse (video_id, h_hash) from player config URLs in HTML
  3. GET player.vimeo.com/video/{video_id}/config?...&transcript=1
     -> extract text_tracks[].url (signed VTT URL, expires ~24h)
  4. GET captions.vimeo.com/captions/{caption_id}.vtt?expires=...&sig=...
     -> download raw VTT
  5. Clean VTT -> plain text
     -> strip timestamps, cue numbers, VTT tags
     -> deduplicate consecutive identical lines
     -> join with spaces
  6. Save: {slug}.vtt, {slug}.txt, {slug}.json
```

**Rate limits:** 0.4s (embed) + 0.3s (config) + 0.3s (VTT) = ~1.0s per session  
**Retry logic:** 3 attempts with exponential backoff (2s base, doubles per retry)  
**Total runtime:** ~5 minutes for 273 sessions

---

## Data Quality Notes

- All 272 transcripts are English auto-generated captions (Vimeo AI)
- Accuracy varies by session — technical/scientific terminology may be misrecognized
- VTT signed URLs expire ~24h after generation; re-run pipeline to refresh
- Some sessions may have multiple videos (playlist format); pipeline uses first video only
- Transcript text is continuous (no paragraph breaks); sentence boundaries preserved

---

*Pipeline by Biomni | AACR 2026 Annual Meeting, San Diego*
