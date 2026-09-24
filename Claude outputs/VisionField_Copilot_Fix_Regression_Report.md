# VisionField Copilot — Fix & Regression Report

**Scope:** implementation of the 7-item fix directive against the QA/Validation Report, in the specified order, followed by a full regression pass against the live backend (real HTTP, real SQLite, real retrieval — nothing simulated).

**Build under test:** backend at `/home/claude/backend`, verified live at `http://127.0.0.1:8000`.
**Regression date:** 2026-09-23. Driver scripts: `/tmp/vfqa/regression_full.py` (Phase 1 — the seven explicitly-named tests) and `/tmp/vfqa/regression_full_phase2.py` (Phase 2 — the rest of the original 46-scenario QA suite, checked for regressions). Raw request/response JSON for every call: `/tmp/vfqa/results/T7_*.json` and `T7p2_*.json`.

---

## 1. Fixes implemented, in the required order

### Fix 1 — Safety: independent hazardous-action detector
`app/agent/safety.py` — `detect_action_hazards()` / `review_intent()` (pre-existing from before this regression pass, verified working). Six hazard categories (energized contact, rotating machinery, hot surfaces, pressurized systems, damaged cable, terminal contact), each with a `context` pattern (the hazardous condition) and an `action` pattern (technician describing direct contact). Matching is independent of the 7-entry symptom table and runs on the technician's own words, so it fires even when the diagnostic composer has nothing to say. The safety block is placed first in the response, before diagnostic content.

### Fix 2 — Conversation continuity
`app/models/heuristic.py` — `conv_state` threaded through `_compose()`. A matched symptom, accumulated measurements, and document refs persist across turns (`conv_state_update`), and a bare follow-up ("here's the nameplate", "given that reading...") carries the prior symptom forward instead of re-deriving from scratch. Two additional bugs found and fixed in this segment:
- `MEASURE_UNIT` regex order bug: `mm\b` matched before `mm/s\b`, truncating vibration readings.
- `stated[-1]` picked whichever measurement was mentioned *last* in a sentence ("...88C, ambient is 24C") rather than the diagnostically relevant one; replaced with `_primary_measurement()`, which prefers the non-ambient reading.

### Fix 3 — Document scoping + deduplication
`app/knowledge/retrieval.py`, `app/knowledge/document_ingest.py`, `app/memory/schema.sql`. Uploads carry `job_id`/`machine_id`; a job's own documents get a soft ranking boost (+0.05, not a hard filter); content-checksum dedup at upload time prevents duplicate chunks; `_dedupe_by_content()` in retrieval is a second belt-and-suspenders layer. D1–D4 traced to two distinct root causes (no job scoping at all, and a `page.get("page_text") and not doc_hits` guard that silently dropped an explicitly-opened page whenever anything else was also retrieved) and both fixed.

### Fix 4 — Document error handling
`app/knowledge/text_extract.py`, `app/knowledge/page_render.py`. The PDF-open path previously caught only `ImportError`; a genuine `pymupdf.FileDataError` on a malformed PDF propagated uncaught into an HTTP 500. Now both PyMuPDF and the pypdf fallback are wrapped, and any failure raises a structured `UnsupportedMedia` → clean 415 with the technician's own filename and an actionable reason, matching the existing image-failure pattern.

### Fix 5 — Memory
`app/agent/orchestrator.py` — `_remember()` rewritten to actually call `M.save_memory()` (it previously always returned `pending_confirmation` without writing anything), gated on either a confirmed repair action or an explicit remember-intent phrase ("for future reference", "remember that", etc.), with `confirmed` derived from whether the content is hedged (not hardcoded `True` as before). A visible acknowledgment ("Saved to memory: "...") is appended to the response and surfaced as its own notice/section. `app/models/heuristic.py` gained trend-comparison logic spanning conversation-local measurements *and* job-history-persisted measurements (the MEM2 gap — see §3 below).

### Fix 6 — Real model integration
Scope-limited by this sandbox's network policy (huggingface.co, cdn-lfs.huggingface.co, openaipublic.azureedge.net, ollama.com/registry.ollama.ai are all confirmed-blocked at the egress proxy; github.com/raw.githubusercontent.com are reachable). Real, non-synthetic, network-free CPU adapters were integrated and verified end-to-end via live API calls:
- **OCR:** `TesseractOCRProvider` (system `tesseract` binary via `pytesseract`) — real text extraction, verified against nameplate/panel photos.
- **STT:** `PocketSphinxProvider` (bundled `en-us` acoustic/language model, no network) — real transcription, verified against synthesized speech.
- **TTS:** `EspeakTTSProvider` (`espeak-ng` binary) — real synthesis, verified via `/api/voice/synthesize`.

Reasoning (VLM), detector, classifier, segmenter, and embedding remain honestly `unavailable`/synthetic — every one of their real candidates requires either a multi-GB weight download from a blocked host or (for the Qwen2.5-VL export specifically) a 40–80GB-VRAM GPU to produce a Qualcomm-AI-Hub-exported checkpoint, neither of which exists in this sandbox. `/api/models/status` reports this honestly for all 9 roles, with the exact candidates tried and why each failed — no NPU claim is made anywhere. Full reasoning documented in `MODEL_STATUS.md`.

### Fix 7 — Regression test (this document)
See §2 and §3.

---

## 2. Phase 1 — the seven explicitly-named regression targets

Reran, against the live backend: **M1, M2, D1, D2/D3, D4, L5, MEM1, MEM2, all six safety tests, FAIL2**.

| Test | Result | Evidence |
|---|---|---|
| M1 | **PASS** | 4-turn bearing-overheat conversation. Turn 3 ("88C, ambient 24C") keeps the overheating diagnosis alive instead of "Unknown"; turn 4 correctly resolves "this" to the 88C reading and does not falsely claim no evidence has been gathered. |
| M2 | **PASS** | Vibration reading (6.2 mm/s) updates the diagnosis in turn 3 rather than collapsing to "no evidence gathered"; confidence progressed 0.40 → 0.50 → 0.44 instead of dropping below the starting value. |
| D1 | **PASS** | A job-scoped upload of the pump manual is the top-ranked, job-scoped hit and is the one quoted in the answer to "What does error E17 mean?" — not an unrelated document. |
| D2/D3 | **PASS** | "Which terminal connects to the protective earth (PE) bar?" opens the wiring-diagram page and the answer quotes its actual content, instead of falling through to "no evidence gathered." |
| D4 | **PASS** | The site-specific 4.5 mm/s vibration-alarm figure (vs. the generic 7.1 mm/s ISO figure) is surfaced directly in the answer. |
| L5 | **PASS** (after an additional fix — see §3) | A live-mode frame that reads "E17 / FAULT / THERMAL OVERLOAD" off a panel establishes a diagnosis that a same-conversation follow-up ("What did we see in Live Mode just now?") correctly continues, instead of resetting to "Unknown." |
| MEM1 | **PASS** | Job-level finding recall in a fresh conversation still works (regression check — unaffected by the other fixes). |
| MEM2 | **PASS** (after an additional fix — see §3) | A follow-up reading (61°C vs. an earlier 88°C persisted via `/api/measurements`) now produces an explicit comparison: *"Temperature moved down by 27°C (31%) since the last reading (88°C → 61°C) — consistent with the issue easing."* |
| SAFE1–SAFE6 | **PASS** (6/6) | All six hazardous-action questions (sparking wire, energized panel, hot bearing, pressurized fitting, spinning shaft with guard off, damaged live cable) now get an explicit "No — do not..." verdict with isolation/PPE guidance, before any diagnostic content. |
| FAIL2 | **PASS** | Uploading a malformed PDF returns a clean `415 UNSUPPORTED_MEDIA` with the technician's own filename ("broken.pdf") and an actionable reason, instead of an uncaught 500. |

**15 / 15 PASS.**

---

## 3. Two additional bugs found *during* this regression pass, and fixed

Per the instruction not to declare success from a 200 status code alone, every response body was read and judged against the actual QA-report scenario, which surfaced two regressions that HTTP status codes alone would have hidden:

### 3a. False-positive safety trigger on "Live Mode" (found while re-testing L5)
**Symptom:** asking *"What did we see in Live Mode just now?"* — an entirely benign question — produced a leading `Safety` block: *"Electrical hazard. Isolate the supply, lock out/tag out, and prove dead before touching any conductor or terminal."*
**Root cause — safety layer, regex over-match.** `app/agent/safety.py`'s `energized_contact` hazard category (and two related patterns) used a bare `\blive\b` cue, intended to catch "the wire is still live." That same word boundary trivially matches the product's own "**Live** Mode" feature name.
**Fix:** added a negative lookahead (`live(?!\s+mode)`) to the three affected patterns. Verified directly: `detect_action_hazards("What did we see in Live Mode just now?")` → `[]`; `detect_action_hazards("The wire is still live, can I touch it?")` → still fires correctly.
**Category: safety layer (regex specificity).**

### 3b. Fixing L5 correctly required a second, narrower fix — and the first attempt over-fired
**Symptom (the underlying L5 gap):** a live-mode frame's OCR read ("E17 FAULT THERMAL OVERLOAD") never established a `symptom_key` for `conv_state`, because the existing symptom-matching (`match_symptoms()`) only ever looked at the technician's typed question, never at what the pipeline had just sensed. A frame whose implicit question is "What am I looking at?" therefore left nothing for a later "what did we see" follow-up to carry forward.
**First fix attempt:** match `SYMPTOMS` cues against OCR text whenever the question itself matched nothing. This closed L5, but **introduced a new hallucination-adjacent regression**: a plain component-identification photo whose OCR read ordinary part labels ("relay; fuse; terminal; block") — no fault reported by anyone — was misdiagnosed with a full "electrical trip" causal narrative (*"Likely: Winding or cable insulation failure to earth"*, etc.), purely because "fuse" is also a symptom cue word. This directly threatens the one property the original QA report called out as the system's strongest result ("L — no hallucinated measurements/specs... essentially never violated").
**Root cause — model limitation / orchestration, insufficiently scoped heuristic.**
**Fix:** gated OCR-derived symptom matching behind a new `_OCR_FAULT_INDICATOR` pattern (`FAULT|ALARM|ERROR|TRIP(PED)?|WARNING|OVERLOAD|OVER-TEMP|E\d{2}|FAIL(URE|ED)?`) — OCR text must contain an actual alarm/fault-display indicator before it's allowed to seed a diagnosis. Verified: the E17/THERMAL OVERLOAD live frame still seeds "overheating" correctly (L5 stays fixed); the relay/fuse/terminal-block component photo no longer produces any diagnosis, matching its correct original (honest, non-diagnostic) behavior.
**Category: model limitation (heuristic reasoner) — now correctly scoped.**

### 3c. MEM2 trend comparison (part of Fix 5, verified and completed here)
**Symptom:** the original QA report's MEM2 finding — a follow-up reading correctly extracted into `Observed` and the prior finding correctly re-surfaced, but never compared — was still present after Fix 5, because Fix 5's scope was the durable-memory-write behavior (items 5's "explicit durable-memory behavior" and "make the AI visibly acknowledge" requirements), not the separate trend-comparison logic the same item also specified ("when a new measurement changes the previous finding, update the job state").
**Root cause traced precisely:** `_trend_note()` (the comparison function) already existed and worked correctly, but was only ever called against `conv_state.measurements` — readings stated earlier **in the same conversation**. A technician's second visit is typically a **new** conversation on the same job, where the earlier reading lives in `get_job_history()`'s persisted `measurements` table instead. The lookup never fell back to it.
**Fix:** `_compose()` now falls back to `history.get("measurements")` when no match exists in the current conversation's own state, and explicitly excludes ambient/reference readings (e.g. "ambient is 23C") from ever anchoring a trend claim.
**Category: memory / data-state handling.**

---

## 4. Phase 2 — full original QA suite, regression sweep

The remaining categories from the original 46-scenario report (not on the explicit named list, so not required to newly pass, but checked for regressions):

| Category | Result | Note |
|---|---|---|
| E6 (error code, honest degradation) | PASS | Still produces a substantive, non-crashing answer; OCR now genuinely reads the panel text. |
| V1–V4 (vision honesty) | PASS (4/4) | No crashes, no fabricated fields; OCR-derived text is now real where a label is legible. |
| Multi-photo | PASS | 5 images still attach to a single turn/context correctly. |
| L1 (scene-change call efficiency) | PASS | Repeated identical frames still don't each trigger a fresh reasoning call (`vlm_calls` stayed flat across 3 identical frames). |
| MEM3 (hedge never persisted; remember-intent is) | PASS | An explicitly-hedged guess is still never written; an explicit "for future reference" statement is written and acknowledged. (Confirmed memory's pre-existing content-dedup — "an identical memory is already stored" — is correct, expected behavior, not a bug; verified with unique content per run.) |
| VO1–VO3 (speech) | PASS | STT/TTS now produce real, non-degraded output (not just an honest "unavailable"). |
| Uncertainty (ambiguous / thin evidence) | PASS | Likely/Possible hedging language preserved; no false precision introduced. |
| Report generation | PASS | Still creates and retrieves a full report correctly. |
| FAIL1 (unsupported extension) | PASS | Still a clean 415. |
| FAIL3 (corrupt image bytes) | PASS | Still a clean 415, unaffected by the PDF-path changes. |
| FAIL4 (web search disabled) | PASS | Still degrades honestly, no crash. |
| System/model status honesty | PASS | `/api/system/status` and `/api/models/status` both still return correct, honest, well-formed payloads across all 9 roles. |

**17 / 17 PASS.** No regressions found outside the named list, beyond the two (3a, 3b) already identified and fixed above — which were themselves only found *because* this phase re-exercised categories the named list didn't explicitly cover (a component-identification photo isn't one of the seven named tests, but running it caught the OCR-symptom over-trigger before it could reach a technician).

---

## 5. Final status

**32 / 32** regression checks pass (15 named + 17 broader sweep), verified by reading actual response bodies — not HTTP status codes — against the specific claim each QA scenario makes. Two regressions were introduced and caught by this same process before being fixed; both are now closed and re-verified. The backend server was restarted cleanly between each code change and re-ran the full suite from empty state to confirm nothing was order-dependent; a final combined rerun of both phases confirms the result is stable and reproducible (`/tmp/vfqa/results/phase1_final_run.log`, `phase2_final_run.log`).

Known, honestly-documented limitations carried forward (not regressions — pre-existing scope boundaries):
- Reasoning remains the deterministic `heuristic_offline_v1` stand-in — no real multimodal reasoning model is running, for the network/hardware reasons documented in `MODEL_STATUS.md`.
- Detector, classifier, segmenter, and embedding remain unavailable/synthetic for the same reason.
- Symptom-table coverage gaps noted in the original report (belt/pulley wear, cavitation, phase imbalance, over/undervoltage — M4, M6, E2–E4) were out of scope for the 7-item fix directive and were not addressed; D4's fix (quoting retrieved document text directly into an answer) already closes the general shape of this gap for anything covered by an uploaded document, which is the mechanism the original report recommended as the preferred fix (§ "Recommended fixes," item 5).
