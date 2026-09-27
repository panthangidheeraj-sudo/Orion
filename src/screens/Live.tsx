import { useCallback, useEffect, useRef, useState } from 'react'
import { CameraStage, type CamState, type CameraStageHandle } from '../ui/CameraStage'
import { VoicePanel, type Line, type Speaker } from '../ui/VoicePanel'
import { Icon } from '../ui/Icon'
import { Cap, Chip } from '../ui/bits'
import { useStore } from '../app/store'
import * as api from '../app/api'
import { listen, speechSupported } from '../app/speech'
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
const CAP_IDLE: CapStatus = { detector: 'idle', ocr: 'idle', tracker: 'idle', reasoning: 'idle' }

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
  const [micOn, setMicOn] = useState(false)
  const [speaker, setSpeaker] = useState<Speaker>('idle')
  const [amplitude, setAmplitude] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [lines, setLines] = useState<Line[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [toggles, setToggles] = useState({ detection: true, ocr: true, tracking: false })
  const [detections, setDetections] = useState<Detection[]>([])
  const [ocrTags, setOcrTags] = useState<OcrTag[]>([])
  const [capStatus, setCapStatus] = useState<CapStatus>(CAP_UNAVAILABLE)
  const [sessionId, setSessionId] = useState<string | null>(null)

  const stageRef = useRef<CameraStageHandle | null>(null)
  const micAudio = useRef<{ ctx: AudioContext; stream: MediaStream; raf: number } | null>(null)
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null)
  const ttsGraph = useRef<{ ctx: AudioContext; analyser: AnalyserNode; raf: number } | null>(null)
  const rec = useRef<{ stop: () => void } | null>(null)
  const startedAt = useRef(Date.now())
  const pollTimer = useRef<number | null>(null)
  const busy = useRef(false)
  const erroredOnce = useRef(false)
  /** Real backend responses that actually ran during this session — the only
   * material `endLive()` is allowed to draw from. */
  const analysisMessages = useRef<Message[]>([])
  const capturedEvidence = useRef<Evidence[]>([])

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

  /* --------------------------------------------------- real backend voice */

  const ensureTtsGraph = useCallback(() => {
    if (ttsGraph.current || !ttsAudioRef.current) return ttsGraph.current
    try {
      const Ctor: typeof AudioContext = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctor()
      const src = ctx.createMediaElementSource(ttsAudioRef.current)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      src.connect(analyser)
      analyser.connect(ctx.destination)
      ttsGraph.current = { ctx, analyser, raf: 0 }
    } catch {
      // No graph — audio still plays, the glow just won't react to it.
    }
    return ttsGraph.current
  }, [])

  const tickTtsLevel = useCallback(() => {
    const g = ttsGraph.current
    if (!g) return
    const buf = new Uint8Array(g.analyser.frequencyBinCount)
    const step = () => {
      g.analyser.getByteTimeDomainData(buf)
      let sum = 0
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v }
      const rms = Math.sqrt(sum / buf.length)
      setAmplitude((prev) => prev * 0.7 + Math.min(1, rms * 6) * 0.3)
      g.raf = requestAnimationFrame(step)
    }
    g.raf = requestAnimationFrame(step)
  }, [])

  /** The only way the AI "speaks": a real synthesis call, a real audio file,
   * a real playback level driving the glow. A degraded result is shown as
   * exactly that — never a browser voice standing in for it. */
  const playTts = useCallback(async (text: string) => {
    try {
      const res = await api.synthesizeSpeech(text)
      if (res.degraded || !res.audioUrl) {
        setSpeaker('unavailable')
        setAmplitude(0)
        window.setTimeout(() => setSpeaker((s) => (s === 'unavailable' ? (micOn ? 'listening' : 'idle') : s)), 2200)
        return
      }
      const el = ttsAudioRef.current
      if (!el) { setSpeaker(micOn ? 'listening' : 'idle'); return }
      el.crossOrigin = 'anonymous'
      el.src = res.audioUrl
      ensureTtsGraph()
      await el.play()
    } catch (err) {
      setSpeaker('error')
      setAmplitude(0)
      toast('Voice playback failed', err instanceof Error ? err.message : 'The local voice service did not respond.')
      window.setTimeout(() => setSpeaker((s) => (s === 'error' ? (micOn ? 'listening' : 'idle') : s)), 2200)
    }
  }, [micOn, toast, ensureTtsGraph])

  const onTtsPlay = useCallback(() => {
    setSpeaker('ai')
    if (ttsGraph.current) tickTtsLevel()
  }, [tickTtsLevel])

  const onTtsEnded = useCallback(() => {
    if (ttsGraph.current) cancelAnimationFrame(ttsGraph.current.raf)
    setAmplitude(0)
    setSpeaker(micOn ? 'listening' : 'idle')
  }, [micOn])

  const onTtsError = useCallback(() => {
    if (ttsGraph.current) cancelAnimationFrame(ttsGraph.current.raf)
    setAmplitude(0)
    setSpeaker('error')
    window.setTimeout(() => setSpeaker((s) => (s === 'error' ? (micOn ? 'listening' : 'idle') : s)), 2000)
  }, [micOn])

  /* --------------------------------------------------- real backend frames */

  useEffect(() => {
    if (cam !== 'live' || !backend.online) {
      setCapStatus(backend.online ? CAP_IDLE : CAP_UNAVAILABLE)
      setSessionId(null)
      return
    }
    let cancelled = false
    void api.liveStart(activeId ?? undefined)
      .then((session) => {
        if (cancelled) { void api.liveStop(session.sessionId); return }
        setSessionId(session.sessionId)
        setCapStatus(CAP_IDLE)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setCapStatus(CAP_UNAVAILABLE)
        toast('Live analysis unavailable', err instanceof Error ? err.message : 'The local backend did not respond.')
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

  const sendFrame = useCallback(async (question?: string, deep?: boolean) => {
    if (!sessionId || busy.current) return
    const frame = await stageRef.current?.captureFrame()
    if (!frame) return
    busy.current = true
    try {
      const result = await api.liveFrame(sessionId, frame.blob, { question, deep })
      erroredOnce.current = false
      setDetections(api.detectionsFromLive(result.detections))
      setOcrTags(api.ocrFromLive(result.textRegions, frame.width, frame.height))
      setCapStatus({
        detector: result.ran.detector ? 'active' : 'idle',
        ocr: result.ran.ocr ? 'active' : 'idle',
        tracker: result.ran.tracker ? 'active' : 'idle',
        reasoning: result.ran.reasoning ? 'active' : 'idle',
      })
      if (result.analysis) {
        const msg = api.toMessage(result.analysis, 'live')
        analysisMessages.current = [...analysisMessages.current, msg].slice(-12)
        const spoken = msg.text || (msg.sections ?? []).map((s) => s.text).join(' ')
        setLines((prev) => [...prev.filter((l) => !l.live), { who: 'AI', text: spoken || 'Analysis complete — see the findings below.' } as Line].slice(-6))
        if (spoken) void playTts(spoken)
        else setSpeaker(micOn ? 'listening' : 'idle')
      } else if (question) {
        setLines((prev) => [...prev.filter((l) => !l.live), { who: 'AI', text: 'I could not analyse that just now — the reasoning model did not respond to this frame.' } as Line].slice(-6))
        setSpeaker(micOn ? 'listening' : 'idle')
      }
    } catch (err) {
      if (!erroredOnce.current) {
        erroredOnce.current = true
        toast('Live analysis unavailable', err instanceof Error ? err.message : 'The local backend stopped responding to live frames.')
      }
      setCapStatus(CAP_UNAVAILABLE)
      if (question) {
        setLines((prev) => [...prev.filter((l) => !l.live), { who: 'AI', text: 'Vision model unavailable — I could not analyse that.' } as Line].slice(-6))
        setSpeaker('error')
        window.setTimeout(() => setSpeaker((s) => (s === 'error' ? (micOn ? 'listening' : 'idle') : s)), 1800)
      }
    } finally {
      busy.current = false
    }
  }, [sessionId, micOn, toast, playTts])

  useEffect(() => {
    if (cam !== 'live' || !sessionId) return
    pollTimer.current = window.setInterval(() => { void sendFrame() }, 1100)
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }, [cam, sessionId, sendFrame])

  const askLive = useCallback((heard: string) => {
    setSpeaker('processing')
    void sendFrame(heard, true)
  }, [sendFrame])

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
        toast('Frame captured, but could not sync to the backend', err instanceof Error ? err.message : 'The local backend refused the photo.')
      }
    } else {
      toast('Frame captured', 'The local backend is offline, so it was kept locally but not analysed.')
    }
  }, [activeId, backend.online, toast])

  /* --------------------------------------------------------------- mic */

  const stopMic = useCallback(() => {
    rec.current?.stop()
    rec.current = null
    if (micAudio.current) {
      cancelAnimationFrame(micAudio.current.raf)
      micAudio.current.stream.getTracks().forEach((t) => t.stop())
      void micAudio.current.ctx.close().catch(() => undefined)
      micAudio.current = null
    }
    setAmplitude(0)
    setMicOn(false)
    setSpeaker('idle')
  }, [])

  const startMic = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const Ctor: typeof AudioContext = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctor()
      const src = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      src.connect(analyser)
      const buf = new Uint8Array(analyser.frequencyBinCount)
      let raf = 0
      const tick = () => {
        analyser.getByteTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128
          sum += v * v
        }
        const rms = Math.sqrt(sum / buf.length)
        setAmplitude((prev) => prev * 0.7 + Math.min(1, rms * 6) * 0.3)
        raf = requestAnimationFrame(tick)
        if (micAudio.current) micAudio.current.raf = raf
      }
      raf = requestAnimationFrame(tick)
      micAudio.current = { ctx, stream, raf }
      setMicOn(true)
      setSpeaker('listening')

      if (speechSupported()) {
        rec.current = listen(
          (text, final) => {
            setSpeaker('listening')
            setLines((prev) => {
              const rest = prev.filter((l) => !l.live)
              const next: Line = final ? { who: 'You', text } : { who: 'You', text, live: true }
              return [...rest, next].slice(-6)
            })
            if (final) askLive(text)
          },
          () => undefined,
        )
      }
    } catch (err) {
      const name = (err as DOMException)?.name
      toast(
        name === 'NotAllowedError' ? 'Microphone access was declined' : 'No microphone available',
        'You can still type in Normal Mode, and the camera keeps working.',
      )
      setMicOn(false)
    }
  }, [toast, askLive])

  useEffect(() => () => {
    stopMic()
    if (ttsAudioRef.current) { ttsAudioRef.current.pause(); ttsAudioRef.current.removeAttribute('src') }
    if (ttsGraph.current) {
      cancelAnimationFrame(ttsGraph.current.raf)
      void ttsGraph.current.ctx.close().catch(() => undefined)
    }
  }, [stopMic])

  /* ---------------------------------------------------------- end & hand off */

  const endLive = () => {
    stopMic()
    ttsAudioRef.current?.pause()
    if (sessionId) { void api.liveStop(sessionId); setSessionId(null) }

    const convoId = activeId ?? newConversation('Live inspection')
    const transcript = lines.filter((l) => !l.live)
    if (transcript.length) {
      addMessage(convoId, {
        id: uid('u'),
        role: 'user',
        at: Date.now(),
        mode: 'live',
        text: transcript.filter((l) => l.who === 'You').map((l) => l.text).join(' ') || 'Live inspection',
      })
    }

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
        text: 'No detections, OCR readings or backend analysis were confirmed while the camera was running. Try again with the local backend online, or describe what you saw.',
      },
      evidence: evidence.length ? evidence.slice(0, 12) : undefined,
      refs: refs.length ? refs : undefined,
      confidence,
      confidenceLabel,
      followUps: verified ? ['Create report'] : undefined,
    }
    addMessage(convoId, summary)
    toast(
      verified ? 'Live session added to the conversation' : 'Live session ended — nothing verified',
      verified
        ? 'Transcript, detections and findings are all in the same thread.'
        : 'No detections or backend analysis were confirmed, so nothing beyond the transcript was added.',
    )
    go('chat')
  }

  const selectedDet = detections.find((d) => d.id === selected)

  return (
    <div className="live">
      <audio ref={ttsAudioRef} hidden onPlay={onTtsPlay} onEnded={onTtsEnded} onError={onTtsError} />

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
              {capStatus.detector === 'unavailable'
                ? (backend.online ? 'Live analysis unavailable — the local backend stopped responding.' : 'Vision model unavailable — the local backend is offline.')
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
          speaker={speaker}
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
              className={micOn ? 'ibtn rec xl' : 'ibtn glass xl'}
              aria-label={micOn ? 'Mute microphone' : 'Unmute microphone'}
              aria-pressed={micOn}
              onClick={() => (micOn ? stopMic() : void startMic())}
            >
              <Icon name="mic" size={24} />
            </button>
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

      {!speechSupported() && micOn && (
        <Chip icon="info" size="sm">Speech recognition is unavailable here — the glow still follows your voice level.</Chip>
      )}

      {active && active.messages.length > 0 && (
        <span className="cap" style={{ textAlign: 'center' }}>
          Continuing “{active.title}” — everything here joins the same conversation
        </span>
      )}
    </div>
  )
}
