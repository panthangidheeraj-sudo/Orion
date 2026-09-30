# Orion

A multimodal AI field-technician assistant, built for the Snapdragon AI Lab Build &
Present Challenge. A technician photographs or films a machine, asks a question by text
or voice, and Orion reads the image, checks the technician's own manuals and job history,
reasons through the fault, and says plainly what it observed, what it only suspects, and
what has to be measured before anyone touches the equipment.

This repository holds the React + TypeScript web app (this folder) and the FastAPI
backend that owns all orchestration (`backend/`).

---

## Three ways Orion runs — and what each one is

Orion reports which of these is actually answering. It never presents one as another.

| | Snapdragon on-device path | Deployed hosted demo | Optional private vision service |
|---|---|---|---|
| Reasoning model | Qwen3-VL-4B-Instruct, in-process through Qualcomm GenieX + QAIRT on the Hexagon NPU (`VF_REASONING_PROVIDER=geniex-qwen3-vl`) | A hosted multimodal model on Groq (`hosted-groq`, `qwen/qwen3.8-27b`), called server-side | Not a reasoning model |
| Where it runs | Windows on Snapdragon (ARM64): X Elite, X Plus 8-Core, X2 Elite | Render: `orion-api` web service | Render: `orion-vision` private service (`render.yaml`) |
| Reported accelerator | `npu: true` only after a real generation runs on the QAIRT plugin | `accelerator: remote`, `npu: false` — always | `npu: false` — CPU only on Render |
| Status | **Implemented; on-hardware validation is pending.** No latency, tokens/s or accuracy figure exists yet | Live, and labelled "Hosted AI" | Optional deployment architecture; detector / OCR / segmentation adapters answer only when their model assets are provisioned |

- The Snapdragon path is implemented and tested against a stand-in of the GenieX API, but
  it has **not** been run on a Snapdragon NPU. See
  [`backend/MODEL_STATUS.md`](backend/MODEL_STATUS.md) for the empty results tables that
  will be filled in only from real smoke-test reports.
- The deployed Render demo uses hosted multimodal reasoning for image understanding. An
  optional private vision service provides detector / OCR / segmentation adapters for
  deployments where those model assets are provisioned. No model weights are in this
  repository, and nothing about the vision service has been validated on Snapdragon
  hardware.
- Nothing hosted is ever described as on-device or as running on an NPU.

---

## Running it

### Web app

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check (tsc -b) + production bundle into dist/
npm run preview    # serve the built bundle
npm run typecheck  # tsc --noEmit
```

In development the app calls `/api/...` on its own origin and the Vite dev server proxies
to the backend, so the browser never makes a direct cross-origin call. Point a build at a
different backend with `VITE_VF_BACKEND` (for example the hosted API's URL).

The backend's shared access key (`VF_ACCESS_TOKEN` on a hosted backend) is **not** a build
variable. The user types it under **Profile → System status**; it is kept in that browser
only.

Optional Google sign-in and Firestore sync are compiled in only when the
`VITE_FIREBASE_*` web-app config is present in `.env.local`. Without it the app works
entirely from `localStorage`.

### Backend (local, Snapdragon or any PC)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main                                # http://127.0.0.1:8756
python scripts/check_models.py                    # what loaded, on which accelerator, and why not
```

With no reasoning model configured the backend still starts, but **nothing interprets a
message without a language model** — Orion says it cannot interpret requests rather than
imitating understanding. Choose one:

- On a Snapdragon (Windows ARM64) machine: `VF_REASONING_PROVIDER=geniex-qwen3-vl`. Full
  steps: [`backend/docs/SNAPDRAGON_SETUP.md`](backend/docs/SNAPDRAGON_SETUP.md).
- Anywhere else, a hosted model: set `VF_REASONING_PROVIDER=hosted-groq` and a
  `GROQ_API_KEY` in the server's environment. See
  [`backend/docs/RENDER.md`](backend/docs/RENDER.md).

### Hosted deployment

`render.yaml` defines `orion-api` (public) and `orion-vision` (private, no public URL).
The frontend is deployed separately as a static site; set `VF_CORS_ORIGINS` on the API to
its origin. A hosted backend sleeps when idle, so the app shows "Waking" or "Connecting"
during a cold start and retries, instead of reporting the service offline immediately.

**Profile → System status** always shows which engine answered, whether it is hosted, its
accelerator, and which roles (detector, OCR, tracker, voice, …) are unavailable, read from
the backend's `/api/models/status` rather than assumed.

Camera, microphone and speech need a secure context — `localhost` counts, but if you open
the dev server from a phone on your LAN, use HTTPS or the browser will refuse the
permissions.

---

## Live Mode

Live Mode is a full-screen camera call with Orion. It is one view of the same
conversation as Normal chat (see [the one rule](#the-one-rule-that-matters)).

**What you see**
- The rear camera (`getUserMedia`, `facingMode: environment`) fills the screen, with real
  permission states — granted, denied, no device, hardware failure — each designed.
- **Orion's aura** sits in the lower part of the camera scene: a single canvas of light,
  composited additively over the video with no card or border. It has four states — idle,
  listening, thinking, speaking. While you speak on desktop it follows the real
  microphone level; on phones (where a second microphone capture can drop the browser's
  recognizer) it follows the recognizer's own interim results instead. While Orion speaks
  it uses a procedural envelope nudged by the speech synthesizer's word events — browser
  speech exposes no output level, and nothing claims to measure one.
- The conversation floats beneath the aura with no background card. A call dock holds three
  controls: **Speak / Send / Stop** (microphone), **Camera**, and **End**.
- A quiet `LIVE ● 00:42` badge, and a **⋯ Live details** button that opens the diagnostics:
  Detection / OCR / Tracking / Reasoning chips, the detection / OCR / tracking toggles, and
  **Capture frame as evidence**.

**Voice loop**
1. Press the microphone. The browser's `SpeechRecognition` listens (Chrome or Edge;
   elsewhere Orion says voice input is unavailable and you can use Normal mode).
2. When you stop, the question is sent **together with the current camera frame** (a JPEG
   grabbed from the video) to `POST /api/live/frame` with `question` and `deep`. With no
   camera session it goes through the normal chat path instead.
3. The reply appears in the panel and is **spoken with the browser's own
   `speechSynthesis`** voice. Stop interrupts listening, a pending answer, or Orion
   mid-sentence, and a reply that arrives for a cancelled turn is dropped, never spoken.
4. Each spoken question and its answer are added to the conversation once, as they happen.

**Evidence and honesty**
- The status chips come from `/api/models/status` and each frame's real `ran` flags:
  `running` only if the role ran on the last frame, `idle` if it is ready but had nothing to
  do, `unavailable` if the backend does not list it as ready.
- The backend runs its detector, tracker and OCR on their own cadence, and calls the
  reasoning model only on a meaningful event (a question, a selected object change, a
  significant scene change, OCR text, ambiguity) — never per frame.
- With no detector or OCR on the backend (the hosted demo), Live draws **no boxes or text
  tags**, does not poll in the background, and sends a frame only when you ask a question;
  the hosted model then reads that frame itself. The hint in Live details says so.
- If the reasoning model does not answer (busy, rate-limited), Orion says so and asks you
  to try again; it never substitutes an invented reply. A session the server has forgotten
  (a hosted backend that restarted) is re-opened once, transparently.
- **End** stops the session and continues in chat. The closing summary contains only what
  the backend actually observed, inferred or asked to confirm during the session (plus any
  frame you explicitly captured); if nothing was verified it says so.

**Current limitations**
- The camera is sampled as still frames over plain HTTP; it is not a video stream, and
  the model sees one frame per question.
- Voice input needs a browser with `SpeechRecognition`; voice output uses whatever voices
  the browser provides. The backend's Whisper / Piper adapters exist, but no speech model is
  installed in the hosted deployment and Live does not use them.
- Detection boxes and OCR overlays appear only on a backend with a detector / OCR
  configured — either models provisioned locally, or an `orion-vision` service with its
  model assets in place. Those adapters have not been validated on Snapdragon hardware.
- On the Snapdragon path, Live Mode's reasoning has not yet been run on the NPU.

---

## What is real, and what is not

**Real**
- The starfield: a canvas engine drawing sparse round points travelling from the outer
  edges to a central vanishing point, at a constant inward rate, snapped to the device-pixel
  grid. It falls back to one painted frame under `prefers-reduced-motion` or the in-app
  Reduce motion switch.
- Chat with photos, streamed from `/api/chat/stream`, so the work trail shown while the
  agent thinks is a list of tools that actually ran ("2 passages from your documents") —
  not invented timings. Answers carry page citations, job memory, a confidence figure and
  the backend's safety notice; figures that were never measured are flagged as values to
  confirm.
- Speech: `SpeechRecognition` for dictation in the composer and for the Live voice loop, and
  `speechSynthesis` for Orion's spoken answers in Live. Both feature-detect and degrade
  quietly.
- Files: real `File` objects, real object URLs for image previews, and manuals ingested by
  the backend — text extracted, every page rendered to an image, chunks indexed — with the
  file card reporting the page count and index state the backend returned.
- Persistence: conversations, file metadata, profile, AI-access toggles and preferences live
  in `localStorage`. With Google sign-in and a Firebase config, profile, settings and
  conversations also sync to Firestore; local data never depends on it.
- Reports: generated from the observations, findings and document references actually
  present in the conversation, and printable (`window.print()` with a print stylesheet).
- Ordinary conversation: the backend's router decides whether a message is conversation,
  a clarifying question or technical work; the frontend renders the backend's `kind` and
  decides nothing itself. A greeting gets a short plain reply with no work trail, sections
  or confidence meter.
- Attachments belong to a message: the composer's chips are files staged for the next
  message and clear when it is sent, while the Files dock lists everything the conversation
  can draw on. `store.ask()` adds a message's attachments to its conversation itself.

**When the backend is unreachable**
- The client has no reasoning of its own. It shows a clearly marked "offline" message
  ("I can't reach the Orion engine right now…") and System status says why. The app never
  invents an answer, a detection or a citation.
- Camera, files and history keep working from the device.

**Not done — see Known gaps below.**

---

## Architecture

```
src/
  app/
    types.ts        domain model — conversations, messages, files, detections
    store.tsx       one React context: routing, conversations, files, prefs, toasts
    useAsk.ts       drives a question through the backend (used by Chat and Live)
    api.ts          the only file that knows the backend exists — streaming, uploads, live frames
    capabilities.ts what this running copy can actually do, from measured state
    cloudSync.ts    optional Google sign-in + Firestore merge
    speech.ts       defensive wrappers over SpeechRecognition / speechSynthesis
    micLevel.ts     real microphone level for the Live aura (desktop only)
    seed.ts         first-run example data
    util.ts         formatting, ids, storage
  lib/              firebase, firebaseAuth, firestore — created only when configured
  ui/               Starfield, TopBar, GooeyNav, Composer, Message, Markdown,
                    FilesDock, ConvoMenu, CameraStage, VoicePanel, VoiceAura, Icon, bits
  screens/          Home, Convo, Chat, Live, Files, DocViewer, Reports, Settings,
                    About, AboutEdge, Onboarding
  styles/
    tokens.css      the design system, as custom properties
    app.css         everything else
    about.css       the About / architecture screens
backend/            FastAPI service — see backend/README.md
render.yaml         Render blueprint: orion-api (public) + orion-vision (private)
```

### The one rule that matters

**Live Mode and Normal Chat are two views of one conversation.** Switching modes never
creates a conversation and never clears context. Ending a Live session appends its findings
to the same thread. If you refactor anything, keep this true.

---

## Design system

Taken from the Design canvas. Plain black ground, dark-grey panels, and **no accent hue** —
the action surface is white (`--vf-invert`) with black text (`--vf-on-invert`). The only
colour in the product is status (success / warning / danger) and the spectral voice and aura
gradient, which is decoration and never carries meaning on its own.

Message bubbles are **translucent** — `--vf-panel-glass` at 42% over the starfield, with a
5px backdrop blur. The blur is not decoration: without it, moving stars travel behind the
copy. It is deliberately light, because a heavy blur averages a sparse starfield away to
flat black.

Measured on the rendered page, the brightest background pixel anywhere text sits is
L = 0.0115, which leaves body text at **14.8:1** and muted metadata at **5.2:1** — both
clear of AA.

All values live in `src/styles/tokens.css`. Nothing hardcodes a colour outside that file
except the voice gradient, the aura and the camera overlays.

### Accessibility

- Text pairs are designed to meet WCAG AA on the dark palette.
- Real `<button>`, `<a href>`, `<input>` + `<label>` and `role="switch"` throughout.
- Status is icon + word + colour, never colour alone.
- 44px minimum touch targets; the Live call-dock buttons are 64px.
- A 2px white focus ring at 2px offset.
- Reduce motion stops the starfield and freezes the aura. It defaults to the OS
  `prefers-reduced-motion` value and can be overridden in either direction.

---

## Known gaps

- Light mode is designed but not implemented — the identity is dark-only in this build.
- The document viewer (`DocViewer.tsx`) still renders placeholder page content. The backend
  already serves the real rendered page at `/api/documents/{id}/pages/{n}` and
  `api.documentPageUrl()` builds the URL, so this is a component change, not a missing
  capability.
- **Snapdragon validation is pending.** The GenieX + QAIRT path is implemented but has not
  run on a Snapdragon NPU; there are no on-device latency, tokens/s or accuracy figures.
  The Device Cloud validation scripts are written but have not been run.
- The hosted demo has no detector, OCR, segmentation, speech-to-text or text-to-speech model
  assets configured, so those roles report unavailable there (the classical tracker and a
  lexical, non-semantic embedding are active and labelled as such).
- Live Mode analyses one still frame per spoken question rather than streaming video, and
  its speech uses the browser's recognizer and voices.
- Chat search covers conversation titles and transcripts, not document contents — the
  backend's `/api/documents/search` would cover it.
- Enabling web search flips the flag the backend reads, but the backend has no search
  provider configured by default, so it reports the tool as turned off rather than fetching.
- Conversations live in the browser's `localStorage`, the backend's SQLite (a cache on the
  hosted deployment, whose disk is wiped on restart) and, when signed in, Firestore.
  `cloudSync.ts` merges the browser copy with Firestore; the backend copy is not
  reconciled across reloads.
- Some source comments and one offline status string in `src/app/capabilities.ts` still say
  the "built-in demo responder" is used when the backend is offline. That wording predates
  the current behaviour (an explicit "offline" message with no invented answer).
