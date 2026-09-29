/**
 * The About page's motion system — one engine, reused by every section,
 * instead of animation code scattered through each one.
 *
 *   data-scene="pin"   A tall section with a sticky, viewport-sized stage.
 *                      --p runs 0 → 1 while the stage is pinned; --e runs
 *                      0 → 1 as the scene slides into view just before that.
 *   data-scene="flow"  An ordinary section. --p runs 0 (its top enters the
 *                      bottom of the view) → 1 (its bottom leaves the top).
 *   data-reveal        Gets `.is-in` the first time it is ~20% visible and is
 *                      then forgotten, so a reveal never re-fires on every
 *                      small scroll. `style="--i: n"` staggers siblings.
 *
 * Everything visual is CSS reading --p (transforms and opacity only). The
 * engine does one read pass per animation frame, only for scenes that are
 * on screen, and only writes --p when it actually changed.
 *
 * Glide scrolling (mouse wheel)
 * -----------------------------
 * A wheel notch jumps the page ~100px at once. With native scrolling the
 * browser moves the page on the compositor while --p is updated on the main
 * thread a frame (or more) later, so the pinned stage and the scroll-driven
 * content drift apart and the animation reads as steppy / low-fps.
 *
 * Instead, wheel input sets a scroll TARGET and every animation frame moves
 * the real scrollTop a frame-rate-independent fraction of the way there, then
 * measures and writes --p in that SAME frame. Each notch becomes ~25 evenly
 * spaced frames of motion, and the page and its animation move in lockstep.
 *
 * Touch, keyboard and any other scroll stay native (phones already have
 * momentum scrolling). Reduce Motion turns gliding off entirely.
 */

import { useEffect } from 'react'

export type SceneListener = (p: number) => void

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

/** Time constant (ms) of the glide: ~63% of the remaining distance per TAU.
 *  Notched wheels get a longer, silkier glide; trackpads (small pixel deltas,
 *  already smoothed by the OS) get a short one so they don't feel floaty. */
const TAU_WHEEL = 150
const TAU_PRECISE = 70
/** Minimum change in --p / --e worth a style write (sub-pixel otherwise). */
const EPS = 0.0002

export function useSceneEngine(
  rootRef: { current: HTMLElement | null },
  listeners: Record<string, SceneListener> = {},
) {
  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const scenes = Array.from(root.querySelectorAll<HTMLElement>('[data-scene]'))
    const visible = new Set<HTMLElement>()
    const lastP = new WeakMap<HTMLElement, number>()
    const lastE = new WeakMap<HTMLElement, number>()
    let raf = 0

    const reduced = () => document.documentElement.classList.contains('reduce-motion')

    const measure = () => {
      raf = 0
      const rootRect = root.getBoundingClientRect()
      const viewH = root.clientHeight
      // Read every rect first, then write — no forced layout between scenes.
      const reads = Array.from(visible, (el) => ({ el, r: el.getBoundingClientRect() }))
      for (const { el, r } of reads) {
        const top = r.top - rootRect.top
        let p: number
        if (el.dataset.scene === 'pin') {
          const run = r.height - viewH
          p = run > 0 ? clamp01(-top / run) : clamp01(-top / Math.max(1, r.height))
          // --e: how far the scene has slid into view before it pins (0 → 1),
          // so its content is already arriving while it scrolls up.
          const e = clamp01((viewH - top) / viewH)
          const prevE = lastE.get(el)
          if (prevE === undefined || Math.abs(prevE - e) > EPS || (e !== prevE && (e === 0 || e === 1))) {
            lastE.set(el, e)
            el.style.setProperty('--e', e.toFixed(5))
          }
        } else {
          p = clamp01((viewH - top) / (viewH + r.height))
        }
        const prev = lastP.get(el)
        // Always land exactly on 0 / 1 so an end state is never left at 0.9998.
        if (prev === undefined || Math.abs(prev - p) > EPS || (p !== prev && (p === 0 || p === 1))) {
          lastP.set(el, p)
          el.style.setProperty('--p', p.toFixed(5))
          const id = el.dataset.sceneId
          if (id && listeners[id]) listeners[id](p)
        }
      }
    }
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure) }

    /* ------------------------------------------------ glide scrolling */
    let glide = 0
    let target = 0
    let current = 0
    let lastSet = 0
    let lastTs = 0
    let tau = TAU_WHEEL

    const stopGlide = () => {
      if (glide) cancelAnimationFrame(glide)
      glide = 0
      lastTs = 0
    }

    const glideStep = (ts: number) => {
      // Someone else moved the page mid-glide (keyboard, find-in-page,
      // a focus jump): hand control back instead of fighting it.
      if (Math.abs(root.scrollTop - lastSet) > 2) {
        stopGlide()
        current = target = root.scrollTop
        schedule()
        return
      }
      const dt = lastTs ? Math.min(50, ts - lastTs) : 1000 / 60
      lastTs = ts
      current += (target - current) * (1 - Math.exp(-dt / tau))
      if (Math.abs(target - current) < 0.25) current = target
      root.scrollTop = current
      lastSet = root.scrollTop
      // Measure in this same frame, so --p matches the scroll position the
      // frame is painted at — no one-frame lag between page and animation.
      if (raf) { cancelAnimationFrame(raf); raf = 0 }
      measure()
      if (current === target) stopGlide()
      else glide = requestAnimationFrame(glideStep)
    }

    const onWheel = (ev: WheelEvent) => {
      if (ev.defaultPrevented || ev.ctrlKey || reduced()) return // pinch-zoom, a11y
      if (Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) return      // sideways gestures stay native
      const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? root.clientHeight : 1
      const dy = ev.deltaY * unit
      const max = root.scrollHeight - root.clientHeight
      if (!glide) current = target = lastSet = root.scrollTop
      const next = Math.max(0, Math.min(max, target + dy))
      if (next === target) return // already at an edge
      ev.preventDefault()
      tau = Math.abs(dy) < 40 ? TAU_PRECISE : TAU_WHEEL
      target = next
      if (!glide) glide = requestAnimationFrame(glideStep)
    }

    // While gliding, the glide loop measures; native scrolls schedule a
    // measure for this frame's animation callbacks.
    //
    // A native scroll can also land far from where it started in a single
    // jump — a scrollbar drag, Page Down/End, or a fast trackpad fling can
    // move the page thousands of pixels in one 'scroll' event. IntersectionObserver
    // delivers its callback asynchronously (spec allows it; Chromium can take
    // more than a frame under load), so `visible` can still be missing a scene
    // the page has already landed on. measure() only touches scenes in
    // `visible`, so until that callback arrives the scene's --p stays at
    // whatever it was last parked at — a stale, wrong frame (e.g. the "Built
    // for Snapdragon" stack showing an earlier or later state than the actual
    // scroll position). Guard against that here with a cheap synchronous
    // bounds check — scenes.length is small (about a dozen) — so a scene is
    // never left waiting on the observer for correctness, only for the
    // "parked at rest" cleanup IO still does when a scene leaves view.
    const onScroll = () => {
      if (glide) return
      const rootRect = root.getBoundingClientRect()
      const margin = rootRect.height * 0.1
      for (const s of scenes) {
        if (visible.has(s)) continue
        const r = s.getBoundingClientRect()
        if (r.bottom >= rootRect.top - margin && r.top <= rootRect.bottom + margin) visible.add(s)
      }
      schedule()
    }

    /* ------------------------------------------------ observers */

    // Only scenes near the view are measured on scroll.
    const sceneIo = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const el = e.target as HTMLElement
          if (e.isIntersecting) visible.add(el)
          else {
            visible.delete(el)
            // Park a scene that scrolled fully past at its end state (and one
            // not reached yet at its start), so a fast fling can't leave it
            // frozen half-way.
            const r = el.getBoundingClientRect()
            const rootTop = root.getBoundingClientRect().top
            const p = r.bottom <= rootTop ? 1 : 0
            lastP.set(el, p)
            el.style.setProperty('--p', String(p))
            if (el.dataset.scene === 'pin') { lastE.set(el, p); el.style.setProperty('--e', String(p)) }
            const id = el.dataset.sceneId
            if (id && listeners[id]) listeners[id](p)
          }
        }
        schedule()
      },
      { root, rootMargin: '10% 0px 10% 0px' },
    )
    scenes.forEach((s) => sceneIo.observe(s))

    // One-shot reveals.
    const revealIo = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue
          e.target.classList.add('is-in')
          revealIo.unobserve(e.target)
        }
      },
      { root, threshold: 0.2, rootMargin: '0px 0px -6% 0px' },
    )
    root.querySelectorAll('[data-reveal]').forEach((el) => revealIo.observe(el))

    root.addEventListener('scroll', onScroll, { passive: true })
    root.addEventListener('wheel', onWheel, { passive: false })
    const ro = new ResizeObserver(() => {
      // Content height changed: keep a pending glide inside the new bounds.
      target = Math.min(target, root.scrollHeight - root.clientHeight)
      schedule()
    })
    ro.observe(root)
    schedule()

    return () => {
      root.removeEventListener('scroll', onScroll)
      root.removeEventListener('wheel', onWheel)
      sceneIo.disconnect()
      revealIo.disconnect()
      ro.disconnect()
      stopGlide()
      if (raf) cancelAnimationFrame(raf)
    }
    // Listeners are read at call time; the engine is set up once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rootRef])
}
