import { useEffect, useRef } from 'react'
import { Icon } from './Icon'

export type Speaker = 'idle' | 'user' | 'ai'
export interface Line { who: 'You' | 'AI'; text: string; live?: boolean }

const SETS: Record<Speaker, { colours: string[]; base: number; dur: number; label: string; icon: string }> = {
  idle: {
    colours: ['rgba(210,214,220,.26)', 'rgba(170,175,183,.20)', 'rgba(225,228,232,.16)'],
    base: 0.18, dur: 5.6, label: 'Ready', icon: 'mic',
  },
  user: {
    colours: ['rgba(255,255,255,.60)', 'rgba(64,150,255,.52)', 'rgba(150,220,255,.40)'],
    base: 0.34, dur: 3.2, label: 'You are speaking', icon: 'mic',
  },
  ai: {
    colours: ['rgba(168,140,255,.60)', 'rgba(240,123,208,.44)', 'rgba(96,160,255,.50)'],
    base: 0.3, dur: 4.0, label: 'VisionField is speaking', icon: 'sparks',
  },
}

const BARS = 40

/**
 * The voice spectrum and the words share one box: the glow is the background,
 * the transcript sits on top of it. Amplitude is the real measured level when
 * the microphone is open, so the field is alive rather than looping.
 */
export function VoicePanel({
  speaker, amplitude = 0, lines, reduceMotion, compact,
}: {
  speaker: Speaker
  amplitude?: number
  lines: Line[]
  reduceMotion: boolean
  compact?: boolean
}) {
  const set = SETS[speaker]
  const barsRef = useRef<HTMLDivElement | null>(null)
  const amp = useRef(amplitude)
  amp.current = amplitude

  useEffect(() => {
    const host = barsRef.current
    if (!host || reduceMotion) return
    const bars = Array.from(host.children) as HTMLElement[]
    let raf = 0
    const start = performance.now()
    const tick = (t: number) => {
      const s = (t - start) / 1000
      const level = set.base + amp.current * 0.85
      for (let i = 0; i < bars.length; i++) {
        const x = i / (bars.length - 1)
        const env = Math.pow(Math.sin(Math.PI * x), 1.5)
        const wobble = 0.55 + 0.45 * Math.sin(s * (2.4 + (i % 5) * 0.18) + i * 0.6)
        const h = Math.max(0.08, env * level * wobble * 2.1)
        bars[i].style.transform = `scaleY(${h.toFixed(3)})`
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [set.base, reduceMotion, speaker])

  const maxBarHeight = compact ? 48 : 84

  return (
    <section className="voicepanel" aria-label="Live voice and transcript">
      <div className="glow" aria-hidden="true">
        {set.colours.map((c, i) => (
          <span
            key={i}
            className="blob"
            style={{
              width: `${[52, 46, 40][i]}%`,
              height: `${[130, 150, 120][i]}%`,
              left: `${[6, 44, 70][i]}%`,
              top: `${[-22, -34, -16][i]}%`,
              background: c,
              animation: reduceMotion ? 'none' : `vf-drift-${'abc'[i]} ${(set.dur * [1, 1.25, 0.9][i]).toFixed(1)}s ease-in-out infinite`,
            }}
          />
        ))}
      </div>
      <div className="bars" ref={barsRef} aria-hidden="true">
        {Array.from({ length: BARS }, (_, i) => (
          <i key={i} style={{ height: maxBarHeight }} />
        ))}
      </div>
      <div className="veil" aria-hidden="true" />

      <div className="content">
        <div className="vhead">
          <Icon name={set.icon} size={13} stroke="#fff" width={1.9} />
          <span className="cap" style={{ color: '#fff' }}>{set.label}</span>
          <span style={{ flex: 1 }} />
          <span className="cap" style={{ color: 'rgba(255,255,255,.55)' }}>Live</span>
        </div>
        <div className="lines">
          {lines.length === 0 && (
            <div className="tline">
              <span className="who" style={{ color: 'var(--vf-overlay-2)' }}>AI</span>
              <span className="what" style={{ color: 'rgba(255,255,255,.7)' }}>
                Say what you are looking at and I will follow along.
              </span>
            </div>
          )}
          {lines.map((l, i) => (
            <div className="tline" key={i}>
              <span className="who" style={{ color: l.who === 'You' ? '#fff' : 'var(--vf-overlay-2)' }}>
                {l.who === 'You' ? 'YOU' : 'AI'}
              </span>
              <span className="what">
                {l.text}
                {l.live && <i style={{ display: 'inline-block', width: 2, height: '1em', marginLeft: 2, verticalAlign: -2, background: 'rgba(255,255,255,.75)', animation: 'vf-blink 1.1s steps(1) infinite' }} />}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
