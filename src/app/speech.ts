/** Thin, defensive wrappers around the browser speech APIs. Both degrade to no-ops. */

type Rec = {
  start: () => void
  stop: () => void
  abort: () => void
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((e: any) => void) | null
  onerror: ((e: any) => void) | null
  onend: (() => void) | null
}

function ctor(): (new () => Rec) | null {
  const w = window as any
  return w.SpeechRecognition || w.webkitSpeechRecognition || null
}

export const speechSupported = () => ctor() !== null
export const ttsSupported = () => typeof window !== 'undefined' && 'speechSynthesis' in window

export interface Listener {
  stop: () => void
}

export function listen(
  onText: (text: string, final: boolean) => void,
  onError?: (reason: string) => void,
): Listener | null {
  const C = ctor()
  if (!C) {
    onError?.('unsupported')
    return null
  }
  let rec: Rec
  try {
    rec = new C()
  } catch {
    onError?.('unavailable')
    return null
  }
  rec.continuous = true
  rec.interimResults = true
  rec.lang = 'en-GB'
  rec.onresult = (e: any) => {
    let interim = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i]
      if (r.isFinal) onText(String(r[0].transcript).trim(), true)
      else interim += r[0].transcript
    }
    if (interim.trim()) onText(interim.trim(), false)
  }
  rec.onerror = (e: any) => onError?.(String(e?.error ?? 'error'))
  try {
    rec.start()
  } catch {
    onError?.('start-failed')
    return null
  }
  return {
    stop: () => {
      try { rec.stop() } catch { /* already stopped */ }
    },
  }
}

export function speak(text: string, onDone?: () => void) {
  if (!ttsSupported()) { onDone?.(); return }
  try {
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 1.02
    u.pitch = 0.95
    u.onend = () => onDone?.()
    u.onerror = () => onDone?.()
    window.speechSynthesis.speak(u)
  } catch {
    onDone?.()
  }
}

export function stopSpeaking() {
  if (ttsSupported()) {
    try { window.speechSynthesis.cancel() } catch { /* nothing to cancel */ }
  }
}
