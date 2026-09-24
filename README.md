# VisionField Copilot

A local-first multimodal AI field-technician assistant. Built for the Snapdragon hackathon.

The UI is complete and runnable. The reasoning layer now talks to the real local backend
in `../backend` when it is running, and falls back to a clearly-marked offline responder
when it is not — so the app is demoable on any machine and never quietly passes the stub
off as the real thing.

---

## Running it

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check + production bundle into dist/
npm run preview    # serve the built bundle
```

The app runs standalone with no backend at all. To get real answers, start the local
service alongside it:

```bash
cd ../backend && python -m app.main     # http://127.0.0.1:8756
```

The front-end probes it on load and whenever the window regains focus. **Profile &
Settings → System status** shows which engine answered, which accelerator it used, and
whether any role is running a deterministic stand-in. Override the address with
`VITE_VF_BACKEND` if you move the port.

No API keys, and nothing leaves the machine: the backend is local-first and its web
research tool is off by default.

Camera, microphone and speech need a secure context — `localhost` counts, but if you open
the dev server from a phone on your LAN, use HTTPS or the browser will refuse the permissions.

---

## What is real and what is stubbed

**Real**
- The starfield: a canvas engine drawing sparse round points travelling from the outer edges
  to a central vanishing point, growing and fading at the centre, then respawning at the rim.
  260–1000 points depending on viewport, snapped to the device-pixel grid so a
  one-pixel star stays a hard point of light rather than an anti-aliased smudge.
  Each travels at a CONSTANT inward rate — speed proportional to radius makes them
  decelerate and pile up at the centre while the rim drains, which looks broken
  within seconds. Crossing times vary 2.6x so arrivals never pulse. Falls back to a single painted frame under
  `prefers-reduced-motion` or the in-app Reduce motion switch.
- The camera: `getUserMedia` with the rear camera, and real permission states —
  granted, denied, no device, and hardware failure each have a designed screen.
- The voice glow: a Web Audio `AnalyserNode` measures actual RMS from the microphone and
  drives the bar heights each frame. It is not a loop.
- Speech: `SpeechRecognition` for the live transcript and dictation in the composer,
  `speechSynthesis` for the assistant's spoken turn. Both feature-detect and degrade quietly.
- Files: real `File` objects, real object URLs for image previews, and a processing pipeline
  that walks each one through uploading → reading → indexing → ready.
- Persistence: conversations, files metadata, profile, AI-access toggles and preferences are
  kept in `localStorage`. Object URLs are deliberately not persisted.
- Reports: generated from the observations, findings and document references actually present
  in the conversation, and printable (`window.print()` has a dedicated print stylesheet).

**Wired to the backend**
- `src/app/api.ts` is the only file that knows the service exists. It streams
  `/api/chat/stream`, so the work trail shown while the agent thinks is a list of tools
  that actually ran — "2 passages from your documents" — rather than invented timings.
  It also uploads documents into the local knowledge vault, stores photos, and drives the
  live-mode frame loop.
- Dropping a manual into Files now really ingests it: the backend extracts the text,
  renders every page to an image and indexes the chunks, and the file card reports the
  page count and index state the backend returned.
- Answers carry real page citations, job memory, a confidence figure and the backend's
  safety notice.

**Ordinary conversation**
- `src/app/conversation.ts` mirrors `backend/app/agent/conversation.py`, so a greeting
  behaves the same whether or not the local service is running. "hi", "thanks", "what can
  you do?" and "are you ChatGPT?" get a short plain reply with no work trail, no sections
  and no confidence meter — and anything naming a symptom, a part or a measurement, or
  arriving with a photo attached, still goes to the full diagnostic path.
- `Message.tsx` renders running text as well as sections. It previously only rendered
  `sections`, so a conversational reply came back as an empty card.
- A conversational turn carries no suggestion chips. The reply already says what to do
  next; a row of buttons under "hello" is the product showing off rather than a technician
  answering. Follow-ups stay under a diagnosis, where they point at a specific page or a
  specific next test.

**Attachments belong to a message, not to the conversation**
- The composer's chips are files staged for the *next* message and clear the moment it is
  sent; the Files dock separately lists everything the conversation can draw on. Chat used
  to derive both from `conversation.fileIds`, so a sent file stayed pinned above the
  composer for the rest of the session.
- `store.ask()` adds a message's attachments to its conversation itself, rather than the
  screen doing it. That also removes a stale-state trap: Home creates a conversation and
  sends in the same tick, before a `useState` update would be visible, which was silently
  producing a second empty conversation on every first message.

**Stubbed — the offline fallback**
- `src/app/assistant.ts` → `planSteps()` and `answer()` still exist, and run only when the
  backend is unreachable. The app toasts when it falls back, and System status says the
  local engine is not running, so a demo cannot mistake one for the other.
- `DEMO_DETECTIONS` / `DEMO_OCR` in the same file stand in for the detector and OCR.
  They are expressed as percentages of the camera frame, so real boxes drop straight in
  at any aspect ratio.
- `src/screens/DocViewer.tsx` renders placeholder page content; a real build renders the
  indexed PDF page there.

---

## Architecture

```
src/
  app/
    types.ts       domain model — conversations, messages, files, detections
    store.tsx      one React context: routing, conversations, files, prefs, toasts
    useAsk.ts      drives a question through the assistant (used by Chat AND Live)
    api.ts         the local backend client — streaming, uploads, live frames
    assistant.ts   offline fallback, used only when the backend is unreachable
    speech.ts      defensive wrappers over SpeechRecognition / speechSynthesis
    seed.ts        first-run example data
    util.ts        formatting, ids, storage
  ui/              Starfield, TopBar, Composer, Message, FilesDock,
                   VoicePanel, CameraStage, primitives
  screens/         Home, Convo, Chat, Live, Files, DocViewer, Reports, Settings,
                   About, Onboarding
  styles/
    tokens.css     the design system, as custom properties
    app.css        everything else
```

### The one rule that matters

**Live Mode and Normal Chat are two views of one conversation.** Switching modes never
creates a conversation and never clears context. `useAsk` is shared by both, and ending a
Live session appends the transcript, the detections and the findings to the same thread.
If you refactor anything, keep this true.

---

## Design system

Taken from the Design canvas. Plain black ground, dark-grey panels, and **no accent hue** —
the action surface is white (`--vf-invert`) with black text (`--vf-on-invert`). The only
colour in the product is status (success / warning / danger) and the spectral voice gradient,
which is decoration and never carries meaning on its own.

Message bubbles are **translucent** — `--vf-panel-glass` at 42% over the starfield, with a
5px backdrop blur. The blur is not decoration: without it, moving stars travel behind the
copy. It is deliberately light, because a heavy blur averages a sparse starfield away to
flat black and the transparency stops reading at all.

Measured on the rendered page, the brightest background pixel anywhere text sits is
L = 0.0115, which leaves body text at **14.8:1** and muted metadata at **5.2:1** — both
clear of AA.

All values live in `src/styles/tokens.css`. Nothing hardcodes a colour outside that file
except the voice gradient and the camera overlays.

### Accessibility

- Every text pair meets WCAG AA on the dark palette; muted metadata is 5.5:1 on panel.
- Real `<button>`, `<a href>`, `<input>` + `<label>` and `role="switch"` throughout.
  No div carries a click handler.
- Status is always icon + word + colour, never colour alone.
- 44px minimum touch targets; the Live microphone is 56px.
- A 2px white focus ring at 2px offset, which reads on the panel, the inset and the black
  ground alike.
- Reduce motion stops the starfield and freezes the glow. It defaults to the OS
  `prefers-reduced-motion` value and can then be overridden in either direction.

---

## Known gaps

- Light mode is designed but not implemented — the identity is dark-only in this build.
- The document viewer still renders placeholder pages. The backend already serves the real
  rendered page at `/api/documents/{id}/pages/{n}` and `api.documentPageUrl()` builds the
  URL, so this is a component change, not a missing capability.
- Live mode's camera loop is not yet posting frames to `/api/live/frame`; `api.liveStart`,
  `liveFrame` and `liveStop` are written and exercised, but `Live.tsx` still draws the demo
  overlays. Photo attachments likewise upload through the store rather than through
  `api.uploadPhoto` into the analyse endpoint.
- Chat search covers titles and transcripts, not document contents — the backend's
  `/api/documents/search` would cover it.
- Enabling web search flips the flag the backend reads, but the backend has no search
  provider configured by default, so it reports the tool as turned off rather than
  fetching.
- With the backend running, conversations live in two places: the browser's `localStorage`
  and the backend's SQLite. They are kept in step by id during a session but are not
  reconciled across reloads.
