# VisionField Copilot — backend

A local-first multimodal field-technician agent. Python + FastAPI, running
entirely on the machine in front of the technician.

> **The VLM is the brain. Everything else is a sense, memory store, or tool.**

The backend owns all orchestration. The front-end sends a question and gets
back a finished, safety-reviewed answer; it never decides which model runs, in
what order, or with what evidence.

```
SEE → RETRIEVE → REASON → VERIFY → GUIDE → REMEMBER
```

---

## Start it

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

It listens on `http://127.0.0.1:8756`. Interactive API docs at `/docs`.

Then, before anything else:

```bash
python scripts/check_models.py
```

That prints exactly what loaded, on which accelerator, and why anything is
missing. **Run it before a demo.** It is the file that stops you claiming
something the machine is not doing.

The front-end finds the service automatically and falls back to its built-in
demo responder when it is not running. Override the address with
`VITE_VF_BACKEND` if you move the port.

---

## It runs with no models installed

This is deliberate, and it is the part worth understanding.

A fresh checkout has no exported models, so six of the nine adapter roles
report `unavailable` and two run **deterministic stand-ins**:

| Role | Without an export | Reported as |
|---|---|---|
| reasoning | rule-based tool selection + evidence-bound composition | `synthetic: true`, `npu: false` |
| embedding | stop-filtered hashed word/trigram bag | `synthetic: true`, `npu: false` |
| tracker | classical IoU/centroid association | `cpu-classical`, not synthetic |
| detector, classifier, segmenter, ocr, stt, tts | unavailable, with a named fallback | §25 error envelope |

Everything still works: documents are ingested, indexed and cited; the agent
loop runs; job memory persists; safety review applies; reports generate. What
you do **not** get is a language model, and nothing anywhere claims otherwise.
`GET /api/models/status` lists which roles are stand-ins, the startup log warns
about them, and every chat response carries a `model` block saying which
provider produced it.

The point is that when you replace the stand-ins with real exports, nothing
around them changes — and if an export fails Compute validation, the honest
answer is already the default rather than an awkward retreat.

See **MODEL_STATUS.md** for the current state and how to validate a model on
the target machine.

---

## Layout

```
backend/
├── app/
│   ├── main.py             FastAPI app, CORS locked to localhost, error envelope
│   ├── config.py           every setting, env-driven; no secrets in source
│   ├── util.py             ids, path containment, log-safe previews
│   ├── errors.py           the §25 structured error shape
│   ├── logging_setup.py    redaction filter — no documents, audio or frames in logs
│   ├── api/                the 20 endpoints
│   ├── agent/              orchestrator, prompts, tools, context, safety, live, conversation
│   ├── models/             the nine adapters + ONNX/QNN runtime + registry
│   ├── metrics.py          the §23 figures this process can measure truthfully
│   ├── knowledge/          ingest, extraction, page rendering, chunking, retrieval, web
│   ├── memory/             SQLite, schema, vector store, memory service
│   ├── tools/              the 19 agent tools
│   └── schemas/            request/response models
├── data/                   database, documents, images, audio, reports, models
├── tests/                  104 tests + the §27 fixtures, no network, isolated data
└── scripts/                run.ps1, check_models.py
```

---

## It holds a normal conversation

A field assistant that answers "hi" with *"I need a bit more before I can
narrow this down"* is behaving like a form. So a message that is purely
conversational short-circuits the whole loop in `app/agent/conversation.py`:
no retrieval, no tool calls, no confidence meter, no hazard banner — just a
short reply, in about half a millisecond.

It runs *before* the reasoning provider, on purpose. A greeting should not
spend an NPU inference or a document search (§8's efficiency argument applies
to idle chat as much as to camera frames), and the answer should not depend on
whether a VLM happens to be exported yet.

A chat turn also carries no suggestion chips — the reply already says what to do
next, and a row of buttons under "hello" is the product showing off rather than a
technician answering. Follow-ups stay under a diagnosis, where they point at a
specific page or a specific next test.

Greetings, thanks, farewells, acknowledgements, "what can you do?" and "are you
ChatGPT?" are all handled, and the last two answer from what is actually there:
the capability reply says whether the vault is empty, and the identity reply
names the real engine, including admitting when it is a deterministic stand-in.

The classifier is deliberately conservative — it only fires when the *whole*
message is conversational, and never when an image is attached:

| Message | Routed to |
|---|---|
| `hi` | conversation |
| `hi, the motor is overheating` | the agent loop |
| `thanks, but the bearing is still grinding` | the agent loop |
| `what can you do?` | conversation |
| `what can you do about the vibration` | the agent loop |
| `What is this?` **with a photo** | the agent loop |

Nobody attaches a photograph to say hello.

---

## How a question is answered

`POST /api/chat` runs the loop in `app/agent/orchestrator.py`:

1. **Build context.** Job context first, then documents, then memory, then web
   — the priority order is fixed and the web is off unless enabled for the turn.
2. **Decide whether tools are needed.** The reasoning model returns tool calls;
   reads run concurrently.
3. **Collect structured evidence.** Every tool returns JSON with `ok`,
   `duration_ms` and a source, and is logged to `tool_calls`.
4. **Reason** over the evidence, with a second round if a diagram needs opening.
5. **Verify.** `app/agent/safety.py` reviews the finished answer regardless of
   which model wrote it.
6. **Guide.** Sections come back as Observed / Likely causes / What to test next
   / Needs confirmation / Evidence.
7. **Remember.** Only confirmed statements become durable, and only through the
   §13 write policy.

`POST /api/chat/stream` sends the same thing as server-sent events, with the
work trail arriving before any text — so the UI shows what the agent is doing
rather than a spinner.

---

## Documents have two representations

Uploading a manual builds both halves at once:

```
data/documents/<document_id>/
  original.pdf
  pages/001.png …          ← visual brain: the agent can look at page 47
  extracted/text.json      ← text brain: chunks, embeddings, vector index
  extracted/ocr.json
  metadata.json
```

`search_documents` finds the passage. `get_document_page` opens the rendered
page as an image and hands it to the VLM as an image input. **The VLM never
receives a filesystem path.**

Retrieval is hybrid — dense similarity fused with BM25 over FTS5 — because a
technician's query is often the exact string printed on the machine. `E17`,
`NSK6203` and `24VDC` have to match literally, and an exact technical token
gets a small ranking bonus so the page that names the code cannot be buried.

Citations point at the page the matching sentence is **printed on**, not the
page the chunk happens to start on: each chunk records where every page's text
sits inside it.

Three things keep the answer honest once a technician has several manuals
loaded rather than one:

- **Term coverage.** Rank fusion alone produces near-identical scores — two
  unrelated passages can land a hundred-thousandth apart, which is a coin flip,
  not a ranking. How much of what was actually asked appears in the passage
  breaks that.
- **Document diversity.** No single document takes more than two of the top
  slots, so a one-page schematic that names the terminal is not buried by a
  long manual with many chunks.
- **A relevance floor.** A passage sharing no word with the question is dropped
  rather than cited. Ranking can always order something; relevance is a
  separate question, and sending someone to a page that does not answer them is
  worse than saying the manuals do not cover it. The response reports
  `irrelevant_dropped` and `no_local_answer`.

---

## Live mode does not run the VLM 30 times a second

Per frame, the backend computes a small scene fingerprint — cheap. It is built
from two **standardised** grids, luma and edge density, because a raw grayscale
grid measures brightness rather than subject: two different dark scenes score
nearly identical and the detector never wakes, while a stationary camera's
auto-exposure shift looks like a whole new scene. Standardising removes global
brightness and contrast, so the number moves when the subject does.

Measured on the test fixtures: a 4px hand shake scores 0.025, a ±30% exposure
swing 0.007, a slight defocus 0.000 — all far below the 0.28 threshold — while
panning from a motor to a control panel scores 0.56.

Then:

| Sense | When it runs |
|---|---|
| detector | on an interval, or when the scene changes |
| tracker | every frame that has detections (classical, near-free) |
| OCR | on a slower interval, or when the scene changes |
| **reasoning model** | **only on a meaningful event** |

The events are exactly the ones the spec lists: the technician asks something,
the selected object changes, the scene changes significantly, OCR reads an
error code or warning text, several low-confidence detections make the scene
ambiguous, or deep inspection is requested — and never twice inside the minimum
gap unless the technician asked directly.

Every frame response returns the decision and its reasons, so the efficiency
story is inspectable:

```json
"vlm": { "should_call_vlm": false, "reasons": [], "suppressed_by_rate_limit": false }
```

A 6-frame session where only 2 frames woke the model is a result you can show.

---

## Knowledge priority

§16 fixes the order, and the agent loop enforces it rather than describing it:

1. the current job context,
2. the technician's documents,
3. local memory and RAG,
4. web research — **only when the first three came up short**, and only when it
   has been enabled for the turn.

The first tool round never reaches for the web. After it, `_local_knowledge_thin`
decides: a manual passage that literally contains the technician's error code,
or anything in job memory, means the answer is already local and the web is not
consulted at all.

---

## Never fabricate

Three separate mechanisms, because one is not enough:

- **The prompt** tells the model to label everything Observed / Likely /
  Possible / Unknown / Needs confirmation, and never to invent a measurement.
- **The safety validator** re-reads the finished answer, collects every number
  with a unit, and flags any that appears in neither the technician's message
  nor a tool result. Cited manual values pass; asserted ones are marked as
  figures to confirm.
- **The store refuses.** `save_measurement` without a value raises rather than
  writing a placeholder, and the §13 write policy rejects speculation, chatter,
  unknown types, missing confidence and missing source metadata — each with the
  reason.

The validator also rewrites any answer containing an instruction to work on
live or moving equipment so that it leads with isolation, and attaches the
relevant hazard notice (electrical, rotating, thermal, pressure, chemical).

---

## Security posture

- **No shell, no filesystem, no eval tool.** The registry is the allowlist;
  an unregistered name never reaches a handler.
- **Arguments are validated** against each tool's JSON schema before the
  handler runs, and every call is timed out.
- **Images are addressed by id**, resolved through the database and re-checked
  for containment. A tool argument cannot aim a model at an arbitrary file.
- **Uploads are identified by content**, not by extension or declared type. A
  renamed executable claiming to be a PDF is refused. Images are decoded and
  re-encoded before they touch disk.
- **Filenames are sanitised and paths contained**; `contained_path` refuses
  anything that escapes its root.
- **`fetch_web_source` refuses loopback, link-local and private addresses**, so
  a fetch tool cannot be used to reach the machine it runs on.
- **A remote reasoning endpoint is refused outright.** The OpenAI-compatible
  adapter checks the host against the loopback interface — local-first means a
  camera frame cannot be posted off the device by configuration mistake.
- **Logs are redacted**: credentials, data URIs and long base64 blobs are
  stripped and every record is truncated.
- **No API keys in source.** The environment is the only channel.
- **CORS is restricted to localhost origins.** This is not a general web API.

---

## API

| | |
|---|---|
| `POST /api/chat` · `/api/chat/stream` | ask the agent |
| `GET` `POST` `/api/conversations` | conversation list and history |
| `POST /api/photo/analyze` · `/analyze-multiple` · `/upload` · `/inspect` | photo mode |
| `POST /api/live/start` · `/frame` · `/stop` · `GET /sessions` | live mode |
| `POST /api/documents/upload` · `GET /api/documents` · `/{id}` · `/{id}/pages/{n}` · `POST /search` | knowledge vault |
| `POST` `GET` `/api/jobs` · `/api/machines` · `/api/inspections` · `/api/findings` · `/api/measurements` | job memory |
| `GET` `POST` `DELETE` `/api/memories` | durable memory |
| `GET` `PATCH` `/api/user` | the local technician and their durable preferences |
| `POST` `GET` `/api/reports` | service reports |
| `POST /api/voice/transcribe` · `/synthesize` | voice |
| `GET /api/system/status` · `/api/models/status` · `/api/metrics` · `/api/health` | status |
| `POST /api/models/reload` | re-probe adapters after an export |
| `GET /api/tools` · `POST /api/tools/call` | the allowlist, and direct invocation |

Live transport is plain HTTP for V1. It can become WebSocket or WebRTC without
the agent changing, because the scheduling lives in `app/agent/live_session.py`
rather than in the transport.

---

## Swapping in a real model

1. Export it — see MODEL_STATUS.md for the current Qualcomm CLI flow.
2. Drop it in `data/models/<model_id>/`.
3. `curl -X POST http://127.0.0.1:8756/api/models/reload`
4. Check `accelerator` and `npu` in `/api/models/status`.

If it says `cpu`, QNN was not applied and the honest claim is CPU. The log will
say why. Nothing in the agent, the tools or the API changes.

To point the reasoning role at a local model server instead (llama.cpp, Ollama,
LM Studio), set `VF_REASONING_PROVIDER=local-openai-compat`. A non-loopback URL
is refused.

---

## Tests

```bash
python -m pytest tests/ -q          # 104 unit and integration tests
```

And against a running server, which is the one to use before a demo:

```bash
python -m app.main &                # in another terminal
python scripts/verify_all.py        # 82 checks over the real HTTP surface
```

`verify_all.py` drives the endpoints the front-end actually uses, in the order a
technician would, and asserts the behaviour the specification asks for rather
than a 200 status: that retrieval cites the right document *and* page, that the
live loop does not wake the model on an unchanged scene but does when the
technician pans or asks, that a measurement without a value is refused, that a
renamed executable is not accepted as a PDF, and that nothing claims the NPU.

104 tests, no network, each on a throwaway data directory. They cover the §14
schema, path traversal, log redaction, honest model status, every §3 candidate
being selectable, both document representations, page-accurate citation,
content-sniffed uploads, the agent loop quoting and citing a manual, the safety
rewrite, invented-figure detection, the memory write policy, refusal of
valueless measurements, live rate limiting, tool allowlisting, SSRF refusal,
streaming order, the §16 priority order, the §23 metric coverage, the
conversational split (including every phrasing that must *not* be mistaken for
chat), retrieval
precision across a five-document vault, the relevance floor, memory
de-duplication, the scene fingerprint's invariance to shake and exposure, and
all ten §27 scenarios.

`tests/fixtures.py` generates the §27 fixtures as code rather than checked-in
binaries — a PCB with silkscreen designators, a motor nameplate, a motor and
gearbox assembly, a control panel, a damaged bearing housing, blurred and
underexposed frames, a text-only manual, a diagram-heavy manual, a wiring
schematic and a 24-page service manual. They are synthetic line art, and the
tests say so: they exercise ingest, the visual-document path and the agent
loop, and they assert that with no vision model loaded the agent *says it
cannot confirm what is in the picture* rather than describing it.

---

## Specification map

| Section | Where |
|---|---|
| §2 agent loop | `app/agent/orchestrator.py` |
| §3, §6 model stack and adapters | `app/models/` |
| §4 Compute-status rule | `MODEL_STATUS.md`, `app/models/runtime.py` |
| §5 ONNX Runtime / QNN | `app/models/runtime.py` |
| §7 photo mode | `app/api/photos.py` |
| §8 live mode | `app/agent/live_session.py` |
| §9 OCR shape | `app/models/ocr.py` |
| §10–12 knowledge and RAG | `app/knowledge/` |
| §13–14 memory and schema | `app/memory/` |
| §15 tools | `app/agent/tool_registry.py`, `app/tools/` |
| §16 web search | `app/knowledge/web_search.py` |
| §17 voice | `app/models/whisper.py`, `tts.py`, `app/api/voice.py` |
| §18–19 reasoning policy and safety | `app/agent/prompts.py`, `safety.py` |
| §20–21 API and structure | `app/api/`, this tree |
| §23 metrics | `app/metrics.py`, `GET /api/metrics` |
| §24 privacy | `config.py`, `util.py`, `logging_setup.py`, `web_tools.py` |
| §25 errors and fallbacks | `app/errors.py`, every adapter |
| §27 scenarios | `tests/test_end_to_end.py` |

---

## What is genuinely not done

Stated plainly, because a hackathon demo is easier to defend than to repair:

- **No model has been compiled or profiled with Qualcomm AI Hub Workbench.**
  Phase 9 of the implementation order is untouched. The ONNX/QNN path is
  written and the accelerator is read back from the runtime, but it has not
  been exercised on Snapdragon hardware from here.
- **Segmentation, EdgeTAM tracking, Whisper and TrOCR load their sessions but
  do not complete inference** — their I/O signatures are bound to the specific
  export, which does not exist yet. Each raises the §25 envelope rather than
  returning something plausible.
- **No NPU, GPU or tokens/sec figures.** Everything else §23 asks for is
  measured — end-to-end and first-token latency, reasoning time, per-tool
  latency, model load time, process CPU and memory, camera and tracking FPS —
  but those three need the device profiler or a real generative model, and
  `/api/metrics` names them as unavailable instead of filling them in.
- **Web search has no default provider.** The interface is there; point
  `VF_WEB_SEARCH_ENDPOINT` at one to enable it.
