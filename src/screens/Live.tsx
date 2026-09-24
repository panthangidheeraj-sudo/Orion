import { useCallback, useEffect, useRef, useState } from 'react'
import { CameraStage, type CamState } from '../ui/CameraStage'
import { VoicePanel, type Line, type Speaker } from '../ui/VoicePanel'
import { Icon } from '../ui/Icon'
import { Cap, Chip } from '../ui/bits'
import { useStore } from '../app/store'
import { DEMO_DETECTIONS, DEMO_OCR, LIVE_PROMPTS } from '../app/assistant'
import { listen, speak, speechSupported, stopSpeaking } from '../app/speech'
import { uid } from '../app/util'
import type { Message } from '../app/types'

export function Live() {
  const { go, active, activeId, newConversation, addMessage, prefs, toast } = useStore()
  const [cam, setCam] = useState<CamState>('idle')
  const [micOn, setMicOn] = useState(false)
  const [speaker, setSpeaker] = useState<Speaker>('idle')
  const [amplitude, setAmplitude] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [lines, setLines] = useState<Line[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [toggles, setToggles] = useState({ detection: true, ocr: true, tracking: false })
  const [promptIndex, setPromptIndex] = useState(0)

  const audio = useRef<{ ctx: AudioContext; stream: MediaStream; raf: number } | null>(null)
  const rec = useRef<{ stop: () => void } | null>(null)
  const startedAt = useRef(Date.now())

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

  const stopMic = useCallback(() => {
    rec.current?.stop()
    rec.current = null
    if (audio.current) {
      cancelAnimationFrame(audio.current.raf)
      audio.current.stream.getTracks().forEach((t) => t.stop())
      void audio.current.ctx.close().catch(() => undefined)
      audio.current = null
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
        if (audio.current) audio.current.raf = raf
      }
      raf = requestAnimationFrame(tick)
      audio.current = { ctx, stream, raf }
      setMicOn(true)
      setSpeaker('user')

      if (speechSupported()) {
        rec.current = listen(
          (text, final) => {
            setSpeaker('user')
            setLines((prev) => {
              const rest = prev.filter((l) => !l.live)
              const next: Line = final ? { who: 'You', text } : { who: 'You', text, live: true }
              return [...rest, next].slice(-6)
            })
            if (final) respond(text)
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
  }, [toast])

  /** The assistant's spoken turn. Deterministic for the demo; swap for the real model. */
  const respond = useCallback((_heard: string) => {
    const text = LIVE_PROMPTS[promptIndex % LIVE_PROMPTS.length]
    setPromptIndex((i) => i + 1)
    setSpeaker('ai')
    setLines((prev) => [...prev.filter((l) => !l.live), { who: 'AI', text } as Line].slice(-6))
    speak(text, () => setSpeaker(micOn ? 'user' : 'idle'))
  }, [micOn, promptIndex])

  useEffect(() => () => { stopMic(); stopSpeaking() }, [stopMic])

  const endLive = () => {
    stopMic()
    stopSpeaking()
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
    const summary: Message = {
      id: uid('a'),
      role: 'assistant',
      at: Date.now(),
      mode: 'live',
      head: `Live session · ${Math.max(1, Math.round(elapsed / 60))} min · ${DEMO_DETECTIONS.length} components detected`,
      sections: [
        {
          kind: 'observed',
          text: `Detected ${DEMO_DETECTIONS.map((d) => d.label.toLowerCase()).join(', ')}. Nameplate read as 1LE1 · 11 kW · 1460 rpm, bearing code 6308-2Z/C3.`,
        },
        { kind: 'next', text: 'Take the axial reading at the drive-end housing and tell me the figure — I will check it against the manual limits.' },
      ],
      evidence: DEMO_DETECTIONS.map((d) => ({ id: uid('e'), caption: `${d.label} · ${d.confidence.toFixed(2)}` })),
      followUps: ['Create report'],
    }
    addMessage(convoId, summary)
    toast('Live session added to the conversation', 'Transcript, detections and findings are all in the same thread.')
    go('chat')
  }

  const selectedDet = DEMO_DETECTIONS.find((d) => d.id === selected)

  return (
    <div className="live">
      <CameraStage
        state={cam}
        elapsed={elapsed}
        detections={DEMO_DETECTIONS.map((d) => (d.id === selected ? { ...d, tone: 'selected' as const } : d))}
        ocr={DEMO_OCR}
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
              {selectedDet ? `${selectedDet.label} is being tracked across frames.` : 'Tap any component to focus the analysis on it.'}
            </span>
          </div>
        )}
      </CameraStage>

      <div className="live-lower">
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
            <button type="button" className="ibtn glass" aria-label="Capture frame" onClick={() => toast('Frame captured', 'Saved to this conversation as evidence.')}>
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
