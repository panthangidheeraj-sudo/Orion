import { useEffect, useRef } from 'react'

interface Star { a: number; r: number; v: number; s: number; t: string; o: number }

/**
 * The signature background: sparse round points travelling from the outer
 * edges toward a central vanishing point, growing and brightening slightly as
 * they close in, fading out at the centre, then respawning at the rim.
 * No trails, no radial lines, no tunnel.
 */
export function Starfield({ reduceMotion }: { reduceMotion: boolean }) {
  const ref = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return

    // The app-level preference decides. It is seeded from the OS on first run
    // (see store.tsx), so honouring it here honours the system too.
    const prefersReduced = reduceMotion

    const tints = ['255,255,255', '240,243,247', '222,228,236', '255,252,246']
    let stars: Star[] = []
    let w = 0
    let h = 0
    let cx = 0
    let cy = 0
    let R = 1
    let raf = 0
    let last = 0
    let dpr = 1
    // Snapping to the device pixel grid is what keeps a one-pixel star a hard
    // point of light instead of an anti-aliased smudge.
    const snap = (v: number) => Math.round(v * dpr) / dpr

    const place = (s: Star, first: boolean): Star => {
      s.a = Math.random() * Math.PI * 2
      // Seeded evenly along the radius on the first fill; afterwards each star
      // re-enters just outside the rim, where the fade-in hides the arrival.
      s.r = R * (first ? 0.05 + Math.random() * 1.1 : 1.02 + Math.random() * 0.18)
      // CONSTANT inward speed. Speed proportional to r (exponential decay) makes
      // stars decelerate toward the centre, so they pile up there while the rim
      // drains — the field goes lopsided within seconds. A constant rate keeps
      // the flux through every radius steady, which is what makes it look even.
      // The 2.6x spread in crossing time is what stops arrivals from pulsing.
      s.v = R * (0.055 + Math.random() * 0.085)
      // Mostly hard one-pixel points, with a scattering of brighter, bigger ones.
      s.s = Math.random() < 0.82 ? 0.34 + Math.random() * 0.5 : 0.95 + Math.random() * 0.85
      s.t = tints[(Math.random() * tints.length) | 0]
      s.o = 0.58 + Math.random() * 0.42
      return s
    }

    const size = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = cv.clientWidth || window.innerWidth
      h = cv.clientHeight || window.innerHeight
      cv.width = Math.round(w * dpr)
      cv.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      cx = w * 0.5
      cy = h * 0.44
      R = Math.sqrt(cx * cx + cy * cy)
      const n = Math.max(260, Math.min(1000, Math.round((w * h) / 1500)))
      const next: Star[] = []
      for (let i = 0; i < n; i++) next.push(place(stars[i] ?? ({} as Star), true))
      stars = next
    }

    const frame = (dt: number) => {
      ctx.clearRect(0, 0, w, h)
      const px = 1 / dpr
      for (const s of stars) {
        if (dt) s.r -= s.v * dt
        if (s.r < R * 0.05) place(s, false)
        const q = s.r / R
        const x = cx + Math.cos(s.a) * s.r
        const y = cy + Math.sin(s.a) * s.r
        const p = 1 - Math.min(1, q)
        const rad = s.s * (0.62 + p * 0.55)
        // A long dissolve into the vanishing point. Constant speed concentrates
        // the field toward the centre (density goes as 1/r); fading over the
        // inner third thins exactly the area the headline and composer sit in.
        const inner = Math.max(0, Math.min(1, (q - 0.05) / 0.3))
        const outer = Math.max(0, Math.min(1, (1.2 - q) / 0.14))
        const alpha = Math.min(1, s.o * (0.55 + p * 0.8) * inner * outer)
        if (alpha <= 0.004) continue
        ctx.fillStyle = `rgba(${s.t},${alpha.toFixed(3)})`
        if (rad <= 0.9) {
          // A crisp square of whole device pixels reads as a point of light;
          // a sub-pixel arc reads as a grey blur.
          const side = Math.max(1, Math.round(rad * 2 * dpr)) * px
          ctx.fillRect(snap(x), snap(y), side, side)
        } else {
          ctx.beginPath()
          ctx.arc(snap(x) + px / 2, snap(y) + px / 2, rad, 0, 6.2832)
          ctx.fill()
        }
      }
    }

    const loop = (ts: number) => {
      const dt = last ? Math.min(0.05, (ts - last) / 1000) : 0.016
      last = ts
      frame(dt)
      raf = window.requestAnimationFrame(loop)
    }

    size()
    if (prefersReduced) {
      frame(0)
    } else {
      raf = window.requestAnimationFrame(loop)
    }

    const onResize = () => {
      size()
      if (prefersReduced) frame(0)
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      if (raf) window.cancelAnimationFrame(raf)
    }
  }, [reduceMotion])

  return (
    <div className="vf-stage" aria-hidden="true">
      <canvas ref={ref} />
      <div className="vf-vig" />
    </div>
  )
}
