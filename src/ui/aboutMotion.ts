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
 * on screen, and only writes --p when it actually changed — so an idle page
 * costs nothing and a scrolling one costs one style update per visible scene.
 */

import { useEffect } from 'react'

export type SceneListener = (p: number) => void

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

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
          if (prevE === undefined || Math.abs(prevE - e) > 0.0004) {
            lastE.set(el, e)
            el.style.setProperty('--e', e.toFixed(4))
          }
        } else {
          p = clamp01((viewH - top) / (viewH + r.height))
        }
        const prev = lastP.get(el)
        if (prev === undefined || Math.abs(prev - p) > 0.0004) {
          lastP.set(el, p)
          el.style.setProperty('--p', p.toFixed(4))
          const id = el.dataset.sceneId
          if (id && listeners[id]) listeners[id](p)
        }
      }
    }
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure) }

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

    root.addEventListener('scroll', schedule, { passive: true })
    const ro = new ResizeObserver(schedule)
    ro.observe(root)
    schedule()

    return () => {
      root.removeEventListener('scroll', schedule)
      sceneIo.disconnect()
      revealIo.disconnect()
      ro.disconnect()
      if (raf) cancelAnimationFrame(raf)
    }
    // Listeners are read at call time; the engine is set up once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rootRef])
}
