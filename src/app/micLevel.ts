/**
 * A real microphone level for the Live aura — nothing is recorded, stored or
 * uploaded; an AnalyserNode is read for its RMS and the stream is closed as
 * soon as listening ends.
 *
 * The browser's SpeechRecognition already owns the microphone while Orion
 * listens. Desktop Chrome/Edge happily share it with a second capture; phone
 * browsers (Android Chrome, iOS Safari) can drop the recognizer when a second
 * capture opens, so there the meter is not opened at all and the aura reacts
 * to the recognizer's own interim-result events instead.
 */

export interface MicMeter {
  /** Current level, 0…1 (speech peaks around 0.6–1). */
  read: () => number
  close: () => void
}

export const micMeterSupported = () =>
  typeof navigator !== 'undefined'
  && !!navigator.mediaDevices?.getUserMedia
  && typeof window !== 'undefined'
  && !!(window.AudioContext || (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext)
  && !/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)

export async function openMicMeter(): Promise<MicMeter | null> {
  if (!micMeterSupported()) return null
  let stream: MediaStream | null = null
  let ctx: AudioContext | null = null
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    })
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    ctx = new AC()
    if (ctx.state === 'suspended') await ctx.resume().catch(() => undefined)
    const src = ctx.createMediaStreamSource(stream)
    const an = ctx.createAnalyser()
    an.fftSize = 512
    an.smoothingTimeConstant = 0.6
    src.connect(an)
    const buf = new Float32Array(an.fftSize)
    let closed = false
    return {
      read: () => {
        if (closed) return 0
        an.getFloatTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
        const rms = Math.sqrt(sum / buf.length)
        // Map roughly -50 dBFS (room) … -12 dBFS (close speech) onto 0…1.
        const db = 20 * Math.log10(rms + 1e-8)
        return Math.min(1, Math.max(0, (db + 50) / 38))
      },
      close: () => {
        if (closed) return
        closed = true
        stream?.getTracks().forEach((t) => t.stop())
        void ctx?.close().catch(() => undefined)
      },
    }
  } catch {
    stream?.getTracks().forEach((t) => t.stop())
    void ctx?.close().catch(() => undefined)
    return null
  }
}
