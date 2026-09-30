import { useEffect, useRef, type RefObject } from 'react'

/**
 * Orion's presence in Live Mode: a large field of light that lives in the
 * camera scene (lower left / lower middle), not inside a card.
 *
 * One <canvas>, one requestAnimationFrame loop, rendered at reduced internal
 * resolution (everything in it is soft, so the upscale only adds softness).
 * No React state is touched per frame. The canvas is composited with
 * `mix-blend-mode: screen`, so its light adds to the video underneath and has
 * no edge of its own.
 *
 * Layers, back to front (all additive):
 *  1. an ambient indigo field that spills into the image
 *  2. four drifting nebula lobes (blue, indigo, violet, a little cyan)
 *  3. three aurora ribbons flowing through the field
 *  4. two tilted orbital arcs that turn slowly around the core
 *  5. waves: soft elliptical rings — outward while Orion speaks (and gently
 *     when you speak), inward while it thinks
 *  6. the core, with a touch of white only at its brightest
 *
 * Everything is driven by one smoothed intensity (0…1) plus per-mode shape
 * parameters. Modes only move targets; phases and intensity are integrated
 * continuously, so state changes never snap or restart.
 *
 *  idle        ≈ 0.15, slow breathing and drift (never still)
 *  processing  ≈ 0.25, focused, orbits pulled in, inward waves
 *  listening   0.35 → 0.75 from the REAL microphone level when a meter is
 *              open (app/micLevel.ts), otherwise from the recognizer's own
 *              interim-result events
 *  speaking    0.55 → 1.0 from a procedural speech envelope, nudged by the
 *              synthesizer's real word-boundary events when it sends them.
 *              Browser speech exposes no output level, and nothing here
 *              claims to measure one.
 */

export type AuraMode = 'idle' | 'listening' | 'processing' | 'speaking'

/** Shared, mutable, read every frame — written by Live.tsx without re-rendering. */
export interface AuraSignal {
  /** Returns the live microphone level 0…1, or null when no meter is open. */
  mic: (() => number) | null
  /** A short burst from a real event (a recognised word, a spoken word). */
  kickLevel: number
  kickAt: number
}

export const createAuraSignal = (): AuraSignal => ({ mic: null, kickLevel: 0, kickAt: 0 })

type RGB = [number, number, number]
const rgba = (c: RGB, a: number) => `rgba(${c[0]},${c[1]},${c[2]},${(a < 0 ? 0 : a > 1 ? 1 : a).toFixed(3)})`
const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

const INDIGO: RGB = [58, 62, 214]
const BLUE: RGB = [52, 110, 255]
const VIOLET: RGB = [128, 92, 255]
const CYAN: RGB = [92, 192, 255]
const PALE: RGB = [196, 208, 255]

const LOBES: { c: RGB; r: number; orbit: number; w: number; ph: number; a: number; sx: number; sy: number }[] = [
  { c: BLUE, r: 0.78, orbit: 0.3, w: 0.19, ph: 0.2, a: 0.42, sx: 1.35, sy: 0.9 },
  { c: VIOLET, r: 0.66, orbit: 0.38, w: -0.15, ph: 2.3, a: 0.4, sx: 1.2, sy: 0.95 },
  { c: INDIGO, r: 0.9, orbit: 0.2, w: 0.11, ph: 4.1, a: 0.46, sx: 1.5, sy: 0.85 },
  { c: CYAN, r: 0.42, orbit: 0.46, w: -0.27, ph: 1.2, a: 0.26, sx: 1.25, sy: 0.8 },
]

const RIBBONS: { c: RGB; off: number; k: number; sp: number; ph: number }[] = [
  { c: VIOLET, off: -0.2, k: 2.6, sp: 1.0, ph: 0 },
  { c: BLUE, off: 0.02, k: 3.3, sp: 1.3, ph: 2.1 },
  { c: CYAN, off: 0.22, k: 2.1, sp: 0.8, ph: 4.0 },
]

/** Per-mode shape: size, internal speed, ribbon energy, orbit spread.
 * The centre never moves — only the radius grows and shrinks around it, and
 * the internal lobes stay on small orbits, so every state lives in the same
 * "presence zone". Size is a fraction of the largest (speaking) radius. */
const SHAPE: Record<AuraMode, { expand: number; speed: number; flow: number; orbit: number }> = {
  idle: { expand: 0.7, speed: 1, flow: 0.5, orbit: 0.55 },
  listening: { expand: 0.82, speed: 1.8, flow: 1.1, orbit: 0.55 },
  processing: { expand: 0.66, speed: 0.6, flow: 0.35, orbit: 0.32 },
  speaking: { expand: 1, speed: 1.35, flow: 1, orbit: 0.5 },
}

interface Wave { born: number; life: number; dir: 1 | -1; s: number }

function targetFor(mode: AuraMode, t: number, sig: AuraSignal, now: number, mic: number, dim: boolean): number {
  const kick = sig.kickLevel * Math.exp(-Math.max(0, now - sig.kickAt) / 260)
  let v: number
  switch (mode) {
    case 'idle': v = 0.15 + 0.035 * Math.sin(t * 0.8); break
    case 'processing': v = 0.25 + 0.06 * Math.pow(0.5 + 0.5 * Math.sin(t * 2.1), 2); break
    case 'listening': v = 0.35 + 0.4 * Math.max(mic, kick * 0.8); break
    case 'speaking': {
      // A syllable-rate envelope inside a slower phrase envelope: a shape for
      // "Orion is talking", not a reading of the speaker output.
      const syll = 0.5 + 0.5 * Math.sin(t * 2 * Math.PI * 2.2) * Math.sin(t * 2 * Math.PI * 0.85 + 1.2)
      const phrase = 0.72 + 0.28 * Math.sin(t * 2 * Math.PI * 0.21)
      v = 0.55 + 0.35 * clamp01(syll * phrase) + 0.12 * kick
      break
    }
  }
  return dim ? v * 0.7 : v
}

export function VoiceAura({
  mode, signal, intensity, dim, reduceMotion, className,
}: {
  mode: AuraMode
  signal: RefObject<AuraSignal>
  /** Optional fixed intensity 0…1; when set it replaces the mode's own level. */
  intensity?: number
  /** Voice unavailable / error: the same living aura, a little quieter. */
  dim?: boolean
  reduceMotion: boolean
  className?: string
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const live = useRef({ mode, intensity, dim })
  live.current = { mode, intensity, dim }
  // Orion's Reduce Motion switch, or the operating system's setting.
  const calm = reduceMotion
    || (typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return

    let W = 1
    let H = 1
    let k = 0.5
    const resize = () => {
      // Half resolution (or less): the field is soft by nature.
      k = Math.min(window.devicePixelRatio || 1, 2) * 0.5
      W = Math.max(2, Math.round(canvas.clientWidth * k))
      H = Math.max(2, Math.round(canvas.clientHeight * k))
      if (canvas.width !== W) canvas.width = W
      if (canvas.height !== H) canvas.height = H
    }
    resize()

    const s = {
      I: 0.12, mic: 0, expand: 0.7, speed: 1, flow: 0.5, orbit: 0.55,
      phase: 0, rphase: 0, last: 0, t: 0, nextWave: 0, lastKick: 0, micPeakAt: 0,
    }
    const waves: Wave[] = []

    const radial = (x: number, y: number, r: number, stops: [number, string][], sx = 1, sy = 1, rot = 0) => {
      ctx.save()
      ctx.translate(x, y)
      if (rot) ctx.rotate(rot)
      ctx.scale(sx, sy)
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r)
      for (const [o, c] of stops) g.addColorStop(o, c)
      ctx.fillStyle = g
      ctx.fillRect(-r, -r, r * 2, r * 2)
      ctx.restore()
    }

    const draw = (now: number) => {
      const I = s.I
      const t = s.t
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, W, H)
      ctx.globalCompositeOperation = 'lighter'
      const cx = W * 0.5
      const cy = H * 0.5
      const breath = 1 + 0.03 * Math.sin(t * 0.8) + 0.015 * Math.sin(t * 0.31 + 1.4)
      // Largest radius (speaking at full energy); everything scales from the fixed centre.
      const R = Math.min(W / 2.3, H / 2) * 0.66 * s.expand * breath * (0.94 + 0.1 * I)

      // 1 — ambient field spilling into the camera image
      radial(cx, cy, R * 1.9, [
        [0, rgba(INDIGO, 0.2 + 0.4 * I)],
        [0.45, rgba([44, 42, 160], 0.1 + 0.2 * I)],
        [1, rgba(INDIGO, 0)],
      ], 1.3, 0.95)

      // 2 — drifting nebula lobes
      for (const L of LOBES) {
        const th = L.ph + L.w * s.phase
        const ox = Math.cos(th) * R * L.orbit * s.orbit
        const oy = Math.sin(th * 1.27) * R * L.orbit * s.orbit * 0.6
        const r = R * L.r * (0.95 + 0.1 * Math.sin(s.phase * 0.7 + L.ph))
        const a = L.a * (0.36 + 1.0 * I)
        radial(cx + ox, cy + oy, r, [[0, rgba(L.c, a)], [0.45, rgba(L.c, a * 0.4)], [1, rgba(L.c, 0)]], L.sx, L.sy, th * 0.2)
      }

      // 3 — aurora ribbons flowing through the field
      for (let i = 0; i < RIBBONS.length; i++) {
        const rb = RIBBONS[i]
        const span = R * 1.55
        const grad = ctx.createLinearGradient(cx - span, 0, cx + span, 0)
        grad.addColorStop(0, rgba(rb.c, 0))
        grad.addColorStop(0.5, rgba(rb.c, 1))
        grad.addColorStop(1, rgba(rb.c, 0))
        ctx.strokeStyle = grad
        const amp = R * (0.1 + 0.2 * I) * s.flow
        ctx.beginPath()
        for (let u = -1; u <= 1.0001; u += 0.04) {
          const env = Math.pow(Math.cos((u * Math.PI) / 2), 1.4)
          const x = cx + u * span
          const y = cy + rb.off * R
            + env * amp * Math.sin(u * rb.k * Math.PI * 0.5 + s.rphase * rb.sp + rb.ph)
            + R * 0.07 * Math.sin(u * 1.4 + s.phase * 0.6 + rb.ph)
          if (u === -1) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        const base = 0.35 + 0.9 * I
        for (const [w, a] of [[0.34, 0.06], [0.15, 0.09], [0.05, 0.12], [0.016, 0.16]] as const) {
          ctx.globalAlpha = clamp01(a * base)
          ctx.lineWidth = Math.max(1, R * w)
          ctx.stroke()
        }
        ctx.globalAlpha = 1
      }

      // 4 — orbital arcs
      ctx.lineCap = 'round'
      for (let j = 0; j < 2; j++) {
        const rx = R * (1.12 + j * 0.28) * (0.95 + 0.1 * I)
        const ry = rx * (0.3 + j * 0.06)
        const tilt = j ? 0.42 : -0.3
        const start = s.phase * (j ? -0.33 : 0.27) + j * 2.2
        const segs = 22
        const spanA = 1.9
        ctx.lineWidth = Math.max(1, 1.3 * k)
        for (let q = 0; q < segs; q++) {
          const a0 = start + (q / segs) * spanA
          const a1 = start + ((q + 1) / segs) * spanA
          const fade = Math.sin((q / segs) * Math.PI)
          ctx.strokeStyle = rgba(PALE, (0.05 + 0.22 * I) * fade)
          ctx.beginPath()
          ctx.ellipse(cx, cy, rx, ry, tilt, a0, a1)
          ctx.stroke()
        }
      }

      // 5 — waves
      for (let i = waves.length - 1; i >= 0; i--) {
        const wv = waves[i]
        const age = (now - wv.born) / 1000 / wv.life
        if (age >= 1) { waves.splice(i, 1); continue }
        const r = wv.dir > 0 ? R * (0.28 + age * 1.45) : R * (1.35 - age * 1.0)
        const a = wv.s * Math.pow(1 - age, 1.6) * (wv.dir > 0 ? Math.min(1, age * 6) : Math.min(1, age * 3))
        ctx.strokeStyle = rgba(wv.dir > 0 ? [150, 170, 255] : [170, 150, 255], a * 0.16)
        ctx.lineWidth = Math.max(1, R * 0.16)
        ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.25, r * 0.78, 0, 0, Math.PI * 2); ctx.stroke()
        ctx.strokeStyle = rgba(PALE, a * 0.18)
        ctx.lineWidth = Math.max(1, R * 0.018)
        ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.25, r * 0.78, 0, 0, Math.PI * 2); ctx.stroke()
      }

      // 6 — core (a little white only at its brightest)
      radial(cx, cy, R * 0.78, [
        [0, rgba([232, 236, 255], 0.05 + 0.28 * I * I + 0.06 * I)],
        [0.2, rgba([140, 158, 255], 0.08 + 0.3 * I)],
        [0.55, rgba(VIOLET, 0.04 + 0.12 * I)],
        [1, rgba(VIOLET, 0)],
      ], 1.45, 0.82)
      ctx.globalCompositeOperation = 'source-over'
    }

    const ro = new ResizeObserver(() => { resize(); draw(performance.now()) })
    ro.observe(canvas)

    let raf = 0
    const tick = (now: number) => {
      const dt = Math.min(0.05, s.last ? (now - s.last) / 1000 : 0.016)
      s.last = now
      s.t += dt
      const { mode: m, intensity: fixed, dim } = live.current
      const sig = signal.current ?? createAuraSignal()
      const sh = SHAPE[m]

      // Microphone: smoothed separately, so a single loud sample never jumps.
      const rawMic = m === 'listening' && sig.mic ? sig.mic() : 0
      s.mic += (rawMic - s.mic) * (1 - Math.exp(-dt / (rawMic > s.mic ? 0.08 : 0.3)))

      const target = typeof fixed === 'number' ? clamp01(fixed) : targetFor(m, s.t, sig, now, s.mic, !!dim)
      s.I += (target - s.I) * (1 - Math.exp(-dt / (target > s.I ? 0.16 : 0.55)))

      const kk = 1 - Math.exp(-dt / 0.8)
      const motion = calm ? 0.12 : 1 // Reduce Motion: the aura only breathes, very slowly
      s.expand += (sh.expand - s.expand) * kk
      s.speed += (sh.speed * (1 + 0.7 * s.I) * motion - s.speed) * kk
      s.flow += ((calm ? 0.3 : sh.flow) - s.flow) * kk
      s.orbit += (sh.orbit - s.orbit) * kk
      s.phase += dt * s.speed * 0.9
      s.rphase += dt * (0.7 + 3 * s.I) * (m === 'listening' ? 1.35 : 1) * motion

      // Waves — never under Reduce Motion.
      if (!calm && waves.length < 7) {
        const kickFresh = sig.kickAt > s.lastKick && now - sig.kickAt < 120
        if (m === 'speaking' && (now > s.nextWave || (kickFresh && now - s.nextWave > -350))) {
          waves.push({ born: now, life: 1.7, dir: 1, s: 0.5 + 0.5 * s.I })
          s.nextWave = now + 560 + Math.random() * 280
        } else if (m === 'listening' && s.mic > 0.45 && now - s.micPeakAt > 420) {
          waves.push({ born: now, life: 1.4, dir: 1, s: 0.35 + 0.4 * s.mic })
          s.micPeakAt = now
        } else if (m === 'listening' && kickFresh && !sig.mic) {
          waves.push({ born: now, life: 1.4, dir: 1, s: 0.45 })
        } else if (m === 'processing' && now > s.nextWave) {
          waves.push({ born: now, life: 1.5, dir: -1, s: 0.55 })
          s.nextWave = now + 1500
        } else if (m === 'idle' && now > s.nextWave) {
          waves.push({ born: now, life: 2.6, dir: 1, s: 0.25 })
          s.nextWave = now + 4200
        }
        if (kickFresh) s.lastKick = sig.kickAt
      }

      draw(now)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [calm]) // eslint-disable-line react-hooks/exhaustive-deps

  return <canvas ref={canvasRef} className={className ? `vf-aura ${className}` : 'vf-aura'} aria-hidden="true" />
}
