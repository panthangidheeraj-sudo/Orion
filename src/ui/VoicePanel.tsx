import { useEffect, useRef, type RefObject } from 'react'
import { Markdown } from './Markdown'
import { VoiceAura, type AuraMode, type AuraSignal } from './VoiceAura'

/**
 * Orion in the Live scene: the aura (a field of light in the camera image)
 * with the conversation floating just beneath it. There is no card — no
 * background, border or edge — only a soft, edgeless veil behind the words
 * for legibility, so the camera continues behind everything.
 *
 * States stay honest: `listening` is driven by the real microphone (or the
 * recognizer's own events), `ai` by the speech synthesizer's callbacks,
 * `processing` covers a real backend request in flight. `unavailable`,
 * `noinput` and `error` keep the aura alive but quieter.
 */
export type Speaker = 'idle' | 'listening' | 'processing' | 'ai' | 'unavailable' | 'noinput' | 'error'
export interface Line { who: 'You' | 'AI'; text: string; live?: boolean }

const LABEL: Record<Speaker, string> = {
  idle: 'Orion is here',
  listening: 'Listening',
  processing: 'Thinking',
  ai: 'Orion is speaking',
  unavailable: 'Voice output unavailable',
  noinput: 'Voice input unavailable in this browser',
  error: 'Voice error',
}

const AURA: Record<Speaker, AuraMode> = {
  idle: 'idle', listening: 'listening', processing: 'processing', ai: 'speaking',
  unavailable: 'idle', noinput: 'idle', error: 'idle',
}

export function VoicePanel({
  speaker, lines, reduceMotion, signal, note,
}: {
  speaker: Speaker
  lines: Line[]
  reduceMotion: boolean
  signal: RefObject<AuraSignal>
  note?: string | null
}) {
  // Keep the newest line in view, from its first word (a long answer is read top-down).
  const linesRef = useRef<HTMLDivElement | null>(null)
  const lastText = lines.length ? `${lines.length}:${lines[lines.length - 1].who}:${lines[lines.length - 1].live ? 'l' : 'f'}` : ''
  useEffect(() => {
    const box = linesRef.current
    const last = box?.lastElementChild as HTMLElement | null
    if (box && last) box.scrollTop = last.offsetTop - box.offsetTop - 18
  }, [lastText])

  const dim = speaker === 'unavailable' || speaker === 'noinput' || speaker === 'error'

  return (
    <section className={`voicescene vs-${speaker}`} aria-label="Live voice and transcript">
      <div className="vs-aura" aria-hidden="true">
        <VoiceAura mode={AURA[speaker]} dim={dim} signal={signal} reduceMotion={reduceMotion} />
      </div>
      <div className="vs-text">
        <div className="vs-state" aria-live="polite"><i aria-hidden="true" />{LABEL[speaker]}</div>
        <div className="lines" ref={linesRef}>
          {lines.length === 0 && (
            <div className="tline ai hint">
              <span className="who">Orion</span>
              <div className="what">Point the camera at the equipment and ask me what you&rsquo;re looking at.</div>
            </div>
          )}
          {lines.map((l, i) => (
            <div className={l.who === 'You' ? 'tline you' : 'tline ai'} key={i}>
              <span className="who">{l.who === 'You' ? 'You' : 'Orion'}</span>
              <div className="what">
                {l.who === 'AI' ? <Markdown text={l.text} /> : l.text}
                {l.live && <i className="vcaret" aria-hidden="true" />}
              </div>
            </div>
          ))}
        </div>
        {note && <div className="vnote">{note}</div>}
      </div>
    </section>
  )
}
