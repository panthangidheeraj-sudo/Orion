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

/* ------------------------------------------------------------------ Live voice */

/** Why speech input stopped, in words a user can act on. */
export function recognitionErrorText(code: string): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone permission was denied. Allow the microphone for this site and try again.'
    case 'audio-capture':
      return 'No microphone was found, or another app is using it.'
    case 'no-speech':
      return 'I did not hear anything. Press the microphone and try again.'
    case 'network':
      return "The browser's speech recognition could not reach its speech service."
    case 'unsupported':
      return 'Voice input is unavailable in this browser.'
    default:
      return 'Speech recognition stopped.'
  }
}

export interface OneShot {
  /** Stop listening and submit what was heard so far. */
  stop: () => void
  /** Stop listening and discard everything. */
  abort: () => void
}

/**
 * Listen for one spoken question (push-to-talk). Audio is handled by the
 * browser's own recognizer; nothing here records or uploads it. `onFinal`
 * fires once, with the whole utterance, when the speaker pauses or `stop()`
 * is called — or with an empty string if nothing was recognised.
 */
export function listenOnce(handlers: {
  onInterim: (text: string) => void
  onFinal: (text: string) => void
  onError: (code: string) => void
}): OneShot | null {
  const C = ctor()
  if (!C) { handlers.onError('unsupported'); return null }
  let rec: Rec
  try { rec = new C() } catch { handlers.onError('unsupported'); return null }
  rec.continuous = false
  rec.interimResults = true
  rec.lang = (typeof navigator !== 'undefined' && navigator.language) || 'en-US'
  let finalText = ''
  let interimText = ''
  let aborted = false
  let done = false
  const finish = () => {
    if (done) return
    done = true
    if (!aborted) handlers.onFinal((finalText || interimText).trim())
  }
  rec.onresult = (e: any) => {
    let fin = ''
    let interim = ''
    for (let i = 0; i < e.results.length; i++) {
      const r = e.results[i]
      if (r.isFinal) fin += r[0].transcript
      else interim += r[0].transcript
    }
    finalText = fin
    interimText = interim
    handlers.onInterim(`${fin}${interim}`.trim())
  }
  rec.onerror = (e: any) => {
    const code = String(e?.error ?? 'error')
    // "aborted" is our own abort(); "no-speech" still ends with an empty final.
    if (code === 'aborted') return
    if (code !== 'no-speech') { aborted = true; done = true; handlers.onError(code) }
  }
  rec.onend = finish
  try { rec.start() } catch { handlers.onError('start-failed'); return null }
  return {
    stop: () => { try { rec.stop() } catch { finish() } },
    abort: () => { aborted = true; done = true; try { rec.abort() } catch { /* already ended */ } },
  }
}

/** Turn a Markdown answer into plain sentences a voice can read. */
export function speakableText(md: string): string {
  return md
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(^|\s)\*([^*\s][^*]*)\*/g, '$1$2')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*[-*•]\s+/gm, '')
    .replace(/^\s*(\d{1,3})[.)]\s+/gm, '$1. ')
    .replace(/\n{2,}/g, '. ')
    .replace(/\n/g, '. ')
    .replace(/\.\s*\./g, '.')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

export interface Speech {
  cancel: () => void
}

/**
 * Speak `text` with the browser's own voice. Long answers are split into
 * sentences (Chrome stops a single long utterance after ~15 s). `onEnd` runs
 * once — after the last sentence, on cancel, or on error (`ok` false).
 */
export function speakAnswer(text: string, cb: {
  onStart?: () => void
  onWord?: () => void
  onEnd: (ok: boolean) => void
}): Speech | null {
  if (!ttsSupported() || typeof SpeechSynthesisUtterance === 'undefined') return null
  const synth = window.speechSynthesis
  const plain = speakableText(text)
  const parts = (plain.match(/[^.!?]+[.!?]*\s*/g) ?? [plain]).map((p) => p.trim()).filter(Boolean)
  // Merge very short fragments so the voice doesn't pause every few words.
  const chunks: string[] = []
  for (const p of parts) {
    const last = chunks[chunks.length - 1]
    if (last && (last.length < 60 || p.length < 20) && last.length + p.length < 220) chunks[chunks.length - 1] = `${last} ${p}`
    else chunks.push(p)
  }
  if (!chunks.length) return null
  let finished = false
  let started = false
  const end = (ok: boolean) => {
    if (finished) return
    finished = true
    cb.onEnd(ok)
  }
  try {
    synth.cancel()
    const lang = (typeof navigator !== 'undefined' && navigator.language) || 'en-US'
    chunks.forEach((c, i) => {
      const u = new SpeechSynthesisUtterance(c)
      u.lang = lang
      u.rate = 1.02
      u.onstart = () => { if (!started) { started = true; cb.onStart?.() } }
      u.onboundary = () => cb.onWord?.()
      u.onerror = (e: any) => {
        const code = String(e?.error ?? '')
        end(code === 'interrupted' || code === 'canceled')
      }
      if (i === chunks.length - 1) u.onend = () => end(true)
      synth.speak(u)
    })
    // Chrome can leave the queue paused after a tab switch.
    if (synth.paused) synth.resume()
  } catch {
    end(false)
    return null
  }
  return {
    cancel: () => {
      try { synth.cancel() } catch { /* nothing queued */ }
      end(true)
    },
  }
}
