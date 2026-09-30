import { useCallback, useEffect, useRef, useState } from 'react'
import { CameraStage, type CamState, type CameraStageHandle } from '../ui/CameraStage'
import { VoicePanel, type Line, type Speaker } from '../ui/VoicePanel'
import { Icon } from '../ui/Icon'
import { Cap, Chip } from '../ui/bits'
import { useStore } from '../app/store'
import * as api from '../app/api'
import {
  listenOnce, recognitionErrorText, speakAnswer, speechSupported, stopSpeaking, ttsSupported,
  type OneShot, type Speech,
} from '../app/speech'
import { uid } from '../app/util'
import type { Detection, DocRef, Evidence, Message, OcrTag } from '../app/types'

/** What the backend told us, last time it told us anything, about each real
 * subsystem — never a guess. `active` means it ran on the most recent frame,
 * `idle` means it is wired up but genuinely had nothing to do that frame
 * (the reasoning model in particular only runs on meaningful events — see
 * backend/app/api/live.py), `unavailable` means the backend could not be
 * reached at all. */
type CapState = 'unavailable' | 'idle' | 'active'
interface CapStatus { detector: CapState; ocr: CapState; tracker: CapState; reasoning: CapState }
const CAP_UNAVAILABLE: CapStatus = { detector: 'unavailable', ocr: 'unavailable', tracker: 'unavailable', reasoning: 'unavailable' }
/** A role is only ever shown as idle/running when /api/models/status listed it as
 * ready — a role whose backend or remote service is not READY stays "unavailable". */
function capsFor(ready: readonly string[] | undefined, ran?: Partial<Record<keyof CapStatus, boolean>>): CapStatus {
  const one = (r: keyof CapStatus): CapState =>
    !ready?.includes(r) ? 'unavailable' : ran?.[r] ? 'active' : 'idle'
  return { detector: one('detector'), ocr: one('ocr'), tracker: one('tracker'), reasoning: one('reasoning') }
}

/** The voice loop's four states, and how each looks in the existing panel. */
type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking'
const SPEAKER: Record<VoiceState, Speaker> = { idle: 'idle', listening: 'listening', processing: 'processing', speaking: 'ai' }
const VOICE_WORD: Record<VoiceState, string> = { idle: 'Idle', listening: 'Listening', processing: 'Processing', speaking: 'Speaking' }
const VOICE_BUTTON: Record<VoiceState, string> = {
  idle: 'Ask Orion by voice',
  listening: 'Stop listening and send',
  processing: 'Cancel',
  speaking: 'Stop speaking',
}

/** The words of an answer, as the Live panel shows and speaks them. */
function answerText(msg: Message): string {
  return (msg.text || [msg.lead, ...(msg.sections ?? []).map((s) => s.text)].filter(Boolean).join('\n')).trim()
}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = window.setTimeout(() => reject(new Error('the backend took too long to answer')), ms)
    p.then((v) => { window.clearTimeout(t); resolve(v) }, (e) => { window.clearTimeout(t); reject(e) })
  })
}

function CapChip({ name, state }: { name: string; state: CapState }) {
  const colour = state === 'active' ? '#7cf29a' : state === 'idle' ? 'rgba(255,255,255,.4)' : 'rgba(255,158,150,.85)'
  const text = state === 'active' ? 'running' : state === 'idle' ? 'idle' : 'unavailable'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <i aria-hidden style={{ width: 6, height: 6, borderRadius: 99, background: colour, display: 'inline-block', flex: 'none' }} />
      <span className="cap" style={{ color: 'rgba(255,255,255,.6)' }}>{name} · {text}</span>
    </span>
  )
}

export function Live() {
  const { go, active, activeId, newConversation, addMessage, prefs, toast, backend } = useStore()
  const [cam, setCam] = useState<CamState>('idle')
  /** The voice loop: idle → listening → processing → speaking → idle. */
  const [voice, setVoice] = useState<VoiceState>('idle')
  const [voiceNote, setVoiceNote] = useState<string | null>(null)
  const [amplitude, setAmplitude] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [lines, setLines] = useState<Line[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [toggles, setToggles] = useState({ detection: true, ocr: true, tracking: false })
  const [detections, setDetections] = useState<Detection[]>([])
  const [ocrTags, setOcrTags] = useState<OcrTag[]>([])
  const [capStatus, setCapStatus] = useState<CapStatus>(CAP_UNAVAILABLE)
  /** Why the last live frame failed, or null while frames are going through. */
  const [frameError, setFrameError] = useState<string | null>(null)
  const readyRef = useRef<readonly string[] | undefined>(backend.ready)
  readyRef.current = backend.ready
  const [sessionId, setSessionId] = useState<string | null>(null)
  const sttSupported = speechSupported()
  const canSpeak = ttsSupported()

  const stageRef = useRef<CameraStageHandle | null>(null)
  const rec = useRef<OneShot | null>(null)
  const speech = useRef<Speech | null>(null)
  /** Mirrors `voice` for callbacks, so a stale closure can't double-submit. */
  const voiceRef = useRef<VoiceState>('idle')
  /** Bumped on every Stop: a reply that arrives for a cancelled turn is dropped, never spoken. */
  const turn = useRef(0)
  const startedAt = useRef(Date.now())
  const pollTimer = useRef<number | null>(null)
  const busy = useRef(false)
  /** True while a spoken question owns the frame pipeline; background polling waits. */
  const questionPending = useRef(false)
  const erroredOnce = useRef(false)
  const decay = useRef<number | null>(null)
  /** Real backend responses that actually ran during this session — the only
   * material `endLive()` is allowed to draw from. */
  const analysisMessages = useRef<Message[]>([])
  /** Spoken questions answered this session (each already in the conversation). */
  const spokenTurns = useRef(0)
  const capturedEvidence = useRef<Evidence[]>([])

  const setVoiceState = useCallback((v: VoiceState) => {
    voiceRef.current = v
    setVoice(v)
    if (v === 'idle' || v === 'processing') setAmplitude(0)
  }, [])

  /** A short pulse on the glow, driven by real events (a recognised word, a spoken word). */
  const pulse = useCallback((level: number) => {
    setAmplitude(level)
    if (decay.current) window.clearTimeout(decay.current)
    decay.current = window.setTimeout(() => setAmplitude(0.12), 260)
  }, [])

  useEffect(() => {
    if (!activeId) newConversation('Live inspection')
  }, [activeId, newConversation])

  useEffect(() => {
    const t = window.setInterval(() => setElapsed(Math.round((Date.now() - startedAt.current) / 1000)), 1000)
    return () => window.clearInterval(t)
  }, [])

  const startCamera = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) { setCam('missing'); return }
    setCam('starting')
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      s.getTracks().forEach((t) => t.stop())
      setCam('live')
    } catch (err) {
      const name = (err as DOMException)?.name
      setCam(name === 'NotFoundError' || name === 'OverconstrainedError' ? 'missing' : name === 'NotAllowedError' ? 'denied' : 'error')
    }
  }, [])

  /* --------------------------------------------------- real backend frames */

  const openSession = useCallback(async (): Promise<string> => {
    const session = await api.liveStart(activeId ?? undefined)
    setSessionId(session.sessionId)
    setFrameError(null)
    setCapStatus(capsFor(readyRef.current))
    return session.sessionId
  }, [activeId])

  useEffect(() => {
    if (cam !== 'live' || !backend.online) {
      setCapStatus(backend.online ? capsFor(readyRef.current) : CAP_UNAVAILABLE)
      setSessionId(null)
      return
    }
    let cancelled = false
    void api.liveStart(activeId ?? undefined)
      .then((session) => {
        if (cancelled) { void api.liveStop(session.sessionId); return }
        setSessionId(session.sessionId)
        setFrameError(null)
        setCapStatus(capsFor(readyRef.current))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setCapStatus(CAP_UNAVAILABLE)
        setFrameError(err instanceof Error ? err.message : 'the Orion backend did not respond')
        toast('Live analysis unavailable', err instanceof Error ? err.message : 'The Orion backend did not respond.')
      })
    return () => {
      cancelled = true
      setSessionId((id) => {
        if (id) void api.liveStop(id)
        return null
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cam, backend.online])

  /**
   * Send one frame. Background polls pass no question; a spoken question
   * passes it and gets the analysis back. A session the server no longer has
   * (a hosted backend restarted or scaled) is re-opened once, transparently.
   */
  const sendFrame = useCallback(async (question?: string): Promise<Message | null | undefined> => {
    if (!sessionId) return undefined
    const frame = await stageRef.current?.captureFrame()
    if (!frame) return undefined
    let sid = sessionId
    const once = () => api.liveFrame(sid, frame.blob, question ? { question, deep: true } : {})
    let result: api.LiveFrameResult
    try {
      try {
        result = await once()
      } catch (err) {
        if (err instanceof api.BackendError && (err.status === 404 || err.status === 410)) {
          sid = await openSession()
          result = await once()
        } else throw err
      }
    } catch (err) {
      const reason = err instanceof Error ? err.message : 'the Orion backend stopped responding'
      setFrameError(reason)
      setCapStatus(CAP_UNAVAILABLE)
      if (!erroredOnce.current) {
        erroredOnce.current = true
        toast('Live analysis unavailable', reason)
      }
      if (question) throw err
      return undefined
    }
    erroredOnce.current = false
    setFrameError(null)
    setDetections(api.detectionsFromLive(result.detections))
    setOcrTags(api.ocrFromLive(result.textRegions, frame.width, frame.height))
    setCapStatus(capsFor(readyRef.current, result.ran))
    if (!result.analysis) return null
    const msg = api.toMessage(result.analysis, 'live')
    // Spoken turns are added to the conversation as their own messages (see ask),
    // so only background analyses feed the end-of-session summary.
    if (!question) analysisMessages.current = [...analysisMessages.current, msg].slice(-12)
    // A background analysis (scene change) is shown, never spoken over the user.
    if (!question) {
      const shown = answerText(msg)
      if (shown && voiceRef.current === 'idle') {
        setLines((prev) => [...prev.filter((l) => !l.live), { who: 'AI', text: shown } as Line].slice(-6))
      }
    }
    return msg
  }, [sessionId, openSession, toast])

  useEffect(() => {
    if (cam !== 'live' || !sessionId) return
    pollTimer.current = window.setInterval(() => {
      if (busy.current || questionPending.current) return
      // With no detector or OCR on this backend (the hosted deployment), a background
      // frame can only wake the reasoning model on a "scene change" — an extra hosted
      // AI call every few seconds that uses up its rate limit, so the user's own spoken
      // question then comes back as the no-model fallback. Frames are sent with a question only.
      const ready = readyRef.current ?? []
      if (!ready.includes('detector') && !ready.includes('ocr')) return
      busy.current = true
      void sendFrame().finally(() => { busy.current = false })
    }, 1100)
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }, [cam, sessionId, sendFrame])

  /* -------------------------------------------------------------- capture */

  const captureFrameEvidence = useCallback(async () => {
    const frame = await stageRef.current?.captureFrame()
    if (!frame) { toast('Could not capture a frame', 'The camera has no live frame to capture right now.'); return }
    const url = URL.createObjectURL(frame.blob)
    capturedEvidence.current = [
      ...capturedEvidence.current,
      { id: uid('e'), caption: `Captured frame · ${new Date().toLocaleTimeString()}`, url },
    ].slice(-8)
    if (backend.online) {
      try {
        await api.uploadPhoto(frame.blob, activeId ?? undefined)
        toast('Frame captured', 'Saved to this conversation as evidence.')
      } catch (err) {
        toast('Frame captured, but could not sync to the backend', err instanceof Error ? err.message : 'The Orion backend refused the photo.')
      }
    } else {
      toast('Frame captured', 'The Orion backend is offline, so it was kept on this device but not analysed.')
    }
  }, [activeId, backend.online, toast])

  /* ------------------------------------------------------------ voice loop */

  const say = useCallback((text: string, myTurn: number) => {
    if (!canSpeak) {
      setVoiceNote('Voice output is unavailable in this browser — the answer is shown as text.')
      setVoiceState('idle')
      return
    }
    setVoiceState('speaking')
    speech.current = speakAnswer(text, {
      onWord: () => pulse(0.55),
      onEnd: (ok) => {
        speech.current = null
        if (turn.current !== myTurn) return
        if (!ok) setVoiceNote('The browser voice could not play this answer — it is shown as text.')
        setVoiceState('idle')
      },
    })
    if (!speech.current) {
      setVoiceNote('The browser voice could not play this answer — it is shown as text.')
      setVoiceState('idle')
    }
  }, [canSpeak, pulse, setVoiceState])

  /** Send one spoken question through the existing Live path (with the current
   * frame) or, with no live camera session, through the normal chat path. */
  const ask = useCallback(async (question: string) => {
    if (voiceRef.current === 'processing' || voiceRef.current === 'speaking') return
    const myTurn = ++turn.current
    setVoiceState('processing')
    setLines((prev) => [...prev.filter((l) => !l.live), { who: 'You', text: question } as Line].slice(-6))
    let msg: Message | null | undefined
    try {
      if (cam === 'live' && sessionId) {
        questionPending.current = true
        // Wait for a background frame already in flight, so the question is never dropped.
        const t0 = Date.now()
        while (busy.current && Date.now() - t0 < 15000) await new Promise((r) => setTimeout(r, 80))
        busy.current = true
        try { msg = await withTimeout(sendFrame(question), 90000) } finally {
          busy.current = false
          questionPending.current = false
        }
      } else {
        const res = await withTimeout(api.ask(question, { mode: 'live', web: false }), 90000)
        msg = res.message
      }
    } catch (err) {
      if (turn.current !== myTurn) return
      const reason = err instanceof Error ? err.message : 'the Orion backend did not answer'
      setLines((prev) => [...prev, { who: 'AI', text: `I could not answer that: ${reason}` } as Line].slice(-6))
      setVoiceState('idle')
      return
    }
    if (turn.current !== myTurn) return
    if (msg?.kind === 'fallback') {
      setLines((prev) => [...prev, { who: 'AI', text: 'The reasoning model did not answer this question just now (the hosted AI may be busy or rate-limited). Ask again in a moment.' } as Line].slice(-6))
      setVoiceState('idle')
      return
    }
    const text = msg ? answerText(msg) : ''
    if (!text) {
      setLines((prev) => [...prev, { who: 'AI', text: 'The reasoning model did not answer this frame. Try asking again.' } as Line].slice(-6))
      setVoiceState('idle')
      return
    }
    setLines((prev) => [...prev, { who: 'AI', text } as Line].slice(-6))
    // Record this turn in the conversation exactly once: the question, then its answer.
    const convoId = activeId ?? newConversation('Live inspection')
    addMessage(convoId, { id: uid('u'), role: 'user', at: Date.now(), mode: 'live', text: question })
    if (msg) addMessage(convoId, msg)
    spokenTurns.current += 1
    say(text, myTurn)
  }, [cam, sessionId, sendFrame, say, setVoiceState, activeId, newConversation, addMessage])

  const startListening = useCallback(() => {
    if (voiceRef.current !== 'idle') return
    setVoiceNote(null)
    if (!sttSupported) {
      setVoiceNote('Voice input is unavailable in this browser. Use Chrome, or type in Normal Mode.')
      return
    }
    setVoiceState('listening')
    rec.current = listenOnce({
      onInterim: (text) => {
        pulse(0.6)
        setLines((prev) => [...prev.filter((l) => !l.live), { who: 'You', text, live: true } as Line].slice(-6))
      },
      onFinal: (text, why) => {
        rec.current = null
        setLines((prev) => prev.filter((l) => !l.live))
        if (!text) {
          setVoiceNote(why ?? recognitionErrorText('no-speech'))
          setVoiceState('idle')
          return
        }
        voiceRef.current = 'idle'
        void ask(text)
      },
      onError: (code) => {
        rec.current = null
        setLines((prev) => prev.filter((l) => !l.live))
        setVoiceNote(recognitionErrorText(code))
        setVoiceState('idle')
      },
    })
    if (!rec.current && (voiceRef.current as VoiceState) === 'listening') setVoiceState('idle')
  }, [sttSupported, ask, pulse, setVoiceState])

  /** The one Stop: ends listening (submitting what was heard), abandons a
   * pending answer's speech, or interrupts Orion mid-sentence. */
  const stopVoice = useCallback(() => {
    const v = voiceRef.current
    if (v === 'listening') { rec.current?.stop(); return }
    turn.current += 1
    speech.current?.cancel()
    speech.current = null
    stopSpeaking()
    setVoiceState('idle')
  }, [setVoiceState])

  useEffect(() => () => {
    rec.current?.abort()
    stopSpeaking()
    if (decay.current) window.clearTimeout(decay.current)
  }, [])

  /* ---------------------------------------------------------- end & hand off */

  const endLive = () => {
    rec.current?.abort()
    turn.current += 1
    stopSpeaking()
    if (sessionId) { void api.liveStop(sessionId); setSessionId(null) }

    const convoId = activeId ?? newConversation('Live inspection')
    // Each spoken question and its answer were already added as they happened.

    const observed: string[] = []
    const inferred: string[] = []
    const needsConfirmation: string[] = []
    const evidence: Evidence[] = [...capturedEvidence.current]
    const refs: DocRef[] = []
    let confidence: number | undefined
    let confidenceLabel: string | undefined

    if (detections.length) {
      observed.push(`Detected ${detections.map((d) => `${d.label} (${Math.round(d.confidence * 100)}%)`).join(', ')}.`)
      detections.forEach((d) => evidence.push({ id: uid('e'), caption: `${d.label} · ${d.confidence.toFixed(2)}` }))
    }
    if (ocrTags.length) {
      observed.push(`Read text: ${ocrTags.map((o) => `“${o.value}”`).join(', ')}.`)
    }
    for (const msg of analysisMessages.current) {
      for (const s of msg.sections ?? []) {
        if (s.kind === 'observed' || s.kind === 'measure') observed.push(s.text)
        else if (s.kind === 'inferred') inferred.push(s.text)
        else if (s.kind === 'next') needsConfirmation.push(s.text)
        else if (s.kind === 'ref') needsConfirmation.push(s.text)
      }
      if (!msg.sections?.length && msg.text) observed.push(msg.text)
      for (const e of msg.evidence ?? []) evidence.push(e)
      for (const r of msg.refs ?? []) {
        if (!refs.some((x) => x.doc === r.doc && x.page === r.page)) refs.push(r)
      }
      if (typeof msg.confidence === 'number') { confidence = msg.confidence; confidenceLabel = msg.confidenceLabel }
    }

    const verified = observed.length > 0 || inferred.length > 0
    const sections: Message['sections'] = []
    if (observed.length) sections.push({ kind: 'observed', text: observed.join(' ') })
    if (inferred.length) sections.push({ kind: 'inferred', text: inferred.join(' ') })
    if (needsConfirmation.length) sections.push({ kind: 'next', text: needsConfirmation.join(' ') })

    const summary: Message = {
      id: uid('a'),
      role: 'assistant',
      at: Date.now(),
      mode: 'live',
      head: `Live session · ${Math.max(1, Math.round(elapsed / 60))} min${detections.length ? ` · ${detections.length} component${detections.length === 1 ? '' : 's'} detected` : ''}`,
      sections: sections.length ? sections : undefined,
      notice: verified ? undefined : {
        level: 'need',
        title: 'Nothing was verified during this live session.',
        text: 'No detections, OCR readings or backend analysis were confirmed while the camera was running. Try again with the Orion backend online, or describe what you saw.',
      },
      evidence: evidence.length ? evidence.slice(0, 12) : undefined,
      refs: refs.length ? refs : undefined,
      confidence,
      confidenceLabel,
      followUps: verified ? ['Create report'] : undefined,
    }
    // Spoken answers are already in the thread; don't follow them with "nothing verified".
    if (verified || !spokenTurns.current) addMessage(convoId, summary)
    toast(
      verified || spokenTurns.current ? 'Live session added to the conversation' : 'Live session ended — nothing verified',
      verified || spokenTurns.current
        ? 'Your questions, answers and findings are all in the same thread.'
        : 'No detections or backend analysis were confirmed, so nothing beyond the transcript was added.',
    )
    go('chat')
  }

  const selectedDet = detections.find((d) => d.id === selected)

  return (
    <div className="live">
      <CameraStage
        ref={stageRef}
        state={cam}
        elapsed={elapsed}
        detections={detections.map((d) => (d.id === selected ? { ...d, tone: 'selected' as const } : d))}
        ocr={ocrTags}
        selectedId={selected}
        onSelect={(id) => setSelected((cur) => (cur === id ? null : id))}
        toggles={toggles}
        onToggle={(k) => setToggles((t) => ({ ...t, [k]: !t[k] }))}
        onRetry={startCamera}
      >
        {cam === 'live' && (
          <div className="scrim-bottom">
            <Icon name="target" size={15} stroke="rgba(255,255,255,.5)" width={1.7} />
            <span style={{ fontSize: 12.5, color: 'rgba(255,255,255,.66)' }}>
              {!backend.online
                ? 'The Orion backend is offline — the camera still works, but frames are not analysed.'
                : frameError
                  ? `Live analysis paused — ${frameError}`
                  : capStatus.detector === 'unavailable'
                    ? 'No detection model on this backend — press the mic and ask, and Orion reads the frame itself.'
                    : selectedDet
                  ? `${selectedDet.label} is being tracked across frames.`
                  : detections.length
                    ? 'Tap any component to focus the analysis on it.'
                    : 'No verified detections yet.'}
            </span>
          </div>
        )}
      </CameraStage>

      <div className="live-lower">
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', padding: '0 2px 8px' }}>
          <CapChip name="Detection" state={capStatus.detector} />
          <CapChip name="OCR" state={capStatus.ocr} />
          <CapChip name="Tracking" state={capStatus.tracker} />
          <CapChip name="Reasoning" state={capStatus.reasoning} />
        </div>

        <VoicePanel
          speaker={!sttSupported && voice === 'idle' ? 'noinput' : SPEAKER[voice]}
          amplitude={amplitude}
          lines={lines}
          reduceMotion={prefs.reduceMotion}
        />

        <div className="live-controls">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="target" size={13} stroke={selectedDet ? 'var(--vf-text)' : 'rgba(255,255,255,.35)'} width={1.9} />
              <Cap style={{ color: selectedDet ? 'var(--vf-text)' : undefined }}>
                {selectedDet ? 'Selected object' : 'No object selected'}
              </Cap>
            </div>
            {selectedDet && (
              <>
                <b style={{ display: 'block', fontSize: 14, marginTop: 6 }}>{selectedDet.label}</b>
                <span className="mono" style={{ fontSize: 10.5, color: 'rgba(255,255,255,.5)' }}>
                  Tracking · {selectedDet.confidence.toFixed(2)} confidence
                </span>
              </>
            )}
          </div>

          <div className="row">
            <button
              type="button"
              className={voice === 'idle' ? 'ibtn glass xl' : 'ibtn rec xl'}
              aria-label={VOICE_BUTTON[voice]}
              title={VOICE_BUTTON[voice]}
              aria-pressed={voice !== 'idle'}
              disabled={voice === 'idle' && !sttSupported}
              onClick={() => (voice === 'idle' ? startListening() : stopVoice())}
            >
              <Icon name={voice === 'idle' || voice === 'listening' ? 'mic' : 'stop'} size={24} />
            </button>
            <span className="cap voice-state" aria-live="polite">{VOICE_WORD[voice]}</span>
            <span style={{ flex: 1 }} />
            <button type="button" className="ibtn glass" aria-label="Capture frame" onClick={() => void captureFrameEvidence()}>
              <Icon name="square" size={19} />
            </button>
            <button
              type="button" className="ibtn glass" aria-label={cam === 'live' ? 'Restart camera' : 'Start camera'}
              onClick={startCamera}
            >
              <Icon name="cam" size={19} />
            </button>
          </div>

          <button type="button" className="endlive" onClick={endLive}>
            <Icon name="stop" size={17} stroke="#ff9e96" width={1.9} />
            End Live &amp; continue in chat
          </button>
        </div>
      </div>

      {(voiceNote || !canSpeak) && (
        <Chip icon="info" size="sm">
          {voiceNote ?? 'Voice output is unavailable in this browser — answers are shown as text.'}
        </Chip>
      )}

      {active && active.messages.length > 0 && (
        <span className="cap" style={{ textAlign: 'center' }}>
          Continuing “{active.title}” — everything here joins the same conversation
        </span>
      )}
    </div>
  )
}
