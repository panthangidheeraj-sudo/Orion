import type { CSSProperties, ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'
import type { Detection, OcrTag } from '../app/types'
import { fmtDuration } from '../app/util'

export type CamState = 'idle' | 'starting' | 'live' | 'denied' | 'missing' | 'error'

const TONE: Record<Detection['tone'], string> = {
  neutral: 'var(--vf-overlay)',
  warn: 'var(--vf-warn)',
  selected: 'var(--vf-overlay)',
}

export function Box({ d, selected, onSelect }: { d: Detection; selected: boolean; onSelect: () => void }) {
  const colour = TONE[d.tone]
  const dashed = d.confidence < 0.7
  return (
    <button
      type="button"
      className="det"
      onClick={onSelect}
      aria-label={`${d.label}, ${Math.round(d.confidence * 100)} per cent confidence${selected ? ', selected' : ''}`}
      style={{
        left: `${d.x}%`, top: `${d.y}%`, width: `${d.w}%`, height: `${d.h}%`,
        borderColor: colour,
        borderStyle: dashed ? 'dashed' : 'solid',
        borderWidth: selected ? 2 : 1,
        background: selected ? 'rgba(255,255,255,0.06)' : 'transparent',
        pointerEvents: 'auto', cursor: 'pointer', padding: 0,
      }}
    >
      {[['left', 'top'], ['right', 'top'], ['left', 'bottom'], ['right', 'bottom']].map(([a, b]) => (
        <span
          key={`${a}${b}`}
          className="corner"
          style={{ [a]: -1, [b]: -1, [`border${a[0].toUpperCase()}${a.slice(1)}`]: `2px solid ${colour}`, [`border${b[0].toUpperCase()}${b.slice(1)}`]: `2px solid ${colour}` } as CSSProperties}
        />
      ))}
      <span className="label" style={{ borderColor: colour, color: colour }}>
        {d.label}
        <span style={{ opacity: 0.8 }}>{d.confidence.toFixed(2)}</span>
      </span>
    </button>
  )
}

export function CameraStage({
  state, elapsed, detections, ocr, selectedId, onSelect, toggles, onToggle, onRetry, children,
}: {
  state: CamState
  elapsed: number
  detections: Detection[]
  ocr: OcrTag[]
  selectedId: string | null
  onSelect: (id: string) => void
  toggles: { detection: boolean; ocr: boolean; tracking: boolean }
  onToggle: (key: 'detection' | 'ocr' | 'tracking') => void
  onRetry: () => void
  children?: ReactNode
}) {
  const video = useRef<HTMLVideoElement | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)

  useEffect(() => {
    if (state !== 'live') return
    let cancelled = false
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return }
        setStream(s)
        if (video.current) {
          video.current.srcObject = s
          void video.current.play().catch(() => undefined)
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      setStream((s) => { s?.getTracks().forEach((t) => t.stop()); return null })
    }
  }, [state])

  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream])

  return (
    <div className="camera">
      {state === 'live' ? (
        <video ref={video} playsInline muted aria-label="Live camera view" />
      ) : (
        <div className="fallback">
          <Icon
            name={state === 'denied' ? 'lock' : state === 'missing' ? 'warn' : 'cam'}
            size={30}
            stroke={state === 'denied' || state === 'missing' ? 'var(--vf-warn)' : 'var(--vf-muted)'}
            width={1.5}
          />
          <div style={{ maxWidth: 420 }}>
            <b style={{ display: 'block', fontSize: 16, marginBottom: 6 }}>
              {state === 'denied' && 'Camera access was declined'}
              {state === 'missing' && 'No camera found on this device'}
              {state === 'error' && 'The camera stopped responding'}
              {(state === 'idle' || state === 'starting') && 'Camera is off'}
            </b>
            <span style={{ fontSize: 13.5, color: 'var(--vf-muted)', lineHeight: 1.6 }}>
              {state === 'denied' && 'Live Mode still works with photos you attach. Re-allow the camera in your browser’s site settings to inspect in real time.'}
              {state === 'missing' && 'Normal Mode, documents and voice all still work.'}
              {state === 'error' && 'Your transcript and captured frames are safe. Try starting the camera again.'}
              {(state === 'idle' || state === 'starting') && 'Camera access lets VisionField inspect equipment in Live Mode — reading nameplates and marking components as you move.'}
            </span>
          </div>
          <button type="button" className="btn primary" onClick={onRetry}>
            <Icon name="cam" size={17} stroke="var(--vf-on-invert)" />
            {state === 'denied' || state === 'error' ? 'Try again' : 'Start camera'}
          </button>
        </div>
      )}

      {state === 'live' && toggles.detection && detections.map((d) => (
        <Box key={d.id} d={d} selected={selectedId === d.id} onSelect={() => onSelect(d.id)} />
      ))}

      {state === 'live' && toggles.ocr && ocr.map((o) => (
        <div className="ocr" key={o.id} style={{ left: `${o.x}%`, top: `${o.y}%` }}>
          <Icon name="text" size={15} stroke="var(--vf-overlay)" width={1.8} />
          <span style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span className="cap" style={{ color: 'rgba(255,255,255,.5)', fontSize: 9 }}>{o.label}</span>
            <span className="mono" style={{ fontSize: 12.5, color: '#fff' }}>{o.value}</span>
          </span>
        </div>
      ))}

      <div className="scrim-top">
        <span className="rec"><i />LIVE {fmtDuration(elapsed)}</span>
        <span style={{ flex: 1 }} />
        {(['detection', 'ocr', 'tracking'] as const).map((k) => (
          <button
            key={k} type="button" className="camtoggle" aria-pressed={toggles[k]}
            onClick={() => onToggle(k)}
          >
            <i />{k}
          </button>
        ))}
      </div>

      {children}
    </div>
  )
}
