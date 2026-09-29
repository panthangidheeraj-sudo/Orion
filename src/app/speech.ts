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
  /** `why` explains an empty result from the events the recognizer actually fired. */
  onFinal: (text: string, why?: string) => void
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
  let stoppedByUser = false
  // Which recognizer events really fired, so an empty result can say why.
  const seen = new Set<string>()
  let lastError = ''
  const note = (ev: string) => {
    if (!seen.has(ev) && typeof console !== 'undefined') console.info(`[orion-voice] ${ev}`)
    seen.add(ev)
  }
  const r = rec as unknown as Record<string, unknown>
  for (const ev of ['start', 'audiostart', 'soundstart', 'speechstart', 'speechend', 'soundend', 'audioend', 'nomatch']) {
    r[`on${ev}`] = () => note(ev)
  }
  const explain = (): string => {
    if (lastError === 'aborted' && !stoppedByUser) return 'Speech recognition was interrupted by the browser before it heard anything. Press the microphone and try again.'
    if (!seen.has('audiostart')) return 'The browser never started capturing audio from the microphone. Check which microphone Chrome is using (Settings → Privacy and security → Site settings → Microphone) and that no other app holds it.'
    if (!seen.has('soundstart')) return 'The microphone is on but only sent silence. Chrome may be using a different or muted input device — pick the right microphone in Chrome’s site settings.'
    if (!seen.has('speechstart')) return 'Sound was picked up but no speech was recognised. Speak closer to the microphone and try again.'
    return 'Speech was heard but the recognizer returned no words. Try again, speaking a full sentence.'
  }
  const finish = () => {
    if (done) return
    done = true
    note('end')
    if (aborted) return
    const text = (finalText || interimText).trim()
    handlers.onFinal(text, text ? undefined : explain())
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
    note('result')
    handlers.onInterim(`${fin}${interim}`.trim())
  }
  rec.onerror = (e: any) => {
    const code = String(e?.error ?? 'error')
    lastError = code
    note(`error:${code}`)
    // "aborted" and "no-speech" end with an empty final, explained from the events seen.
    if (code === 'aborted' || code === 'no-speech') return
    aborted = true
    done = true
    handlers.onError(code)
  }
  rec.onend = finish
  try { rec.start() } catch { handlers.onError('start-failed'); return null }
  return {
    stop: () => { stoppedByUser = true; try { rec.stop() } catch { finish() } },
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

/* Chrome fills the voice list asynchronously; keep a copy so the first answer
   can already use a good voice. */
let voices: SpeechSynthesisVoice[] = []
function loadVoices() {
  try { voices = window.speechSynthesis.getVoices() } catch { voices = [] }
}
if (ttsSupported()) {
  loadVoices()
  try { window.speechSynthesis.addEventListener('voiceschanged', loadVoices) } catch { /* old browsers */ }
}

/** Voices that are clear and full-volume in Chrome, best first. The legacy
 * Windows desktop voices ("Microsoft David/Zira Desktop") and eSpeak-style
 * voices are noticeably quieter and harsher, so they are only a last resort. */
const PREFERRED = [
  /Google US English/i, /Google UK English Female/i, /Google UK English Male/i,
  /Microsoft .*Online \(Natural\)/i, /Microsoft (Aria|Jenny|Guy|Sonia|Ryan|Neerja|Prabhat)/i,
  /Samantha/i, /Daniel/i, /Karen/i,
]
const QUIET = [/Desktop/i, /espeak/i]

/** A clear English voice for `lang`, or null to let the browser choose. */
export function pickVoice(lang: string): SpeechSynthesisVoice | null {
  if (!voices.length) loadVoices()
  const english = voices.filter((v) => /^en([-_]|$)/i.test(v.lang))
  if (!english.length) return null
  const base = lang.toLowerCase().replace('_', '-')
  const score = (v: SpeechSynthesisVoice) => {
    let n = 0
    const i = PREFERRED.findIndex((re) => re.test(v.name))
    if (i >= 0) n += 100 - i
    if (QUIET.some((re) => re.test(v.name))) n -= 60
    if (v.lang.toLowerCase().replace('_', '-') === base) n += 20
    if (v.default) n += 5
    return n
  }
  return [...english].sort((a, b) => score(b) - score(a))[0] ?? null
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
    const voice = pickVoice(lang)
    chunks.forEach((c, i) => {
      const u = new SpeechSynthesisUtterance(c)
      u.lang = voice?.lang || lang
      if (voice) u.voice = voice
      u.volume = 1 // the maximum SpeechSynthesis allows; never rely on the default
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
