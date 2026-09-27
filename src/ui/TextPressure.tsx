// Component ported from React Bits <TextPressure /> (JS + CSS variant),
// itself ported from https://codepen.io/JuanFuentes/full/rgXKGQ
//
// Changes from the upstream source, all for Orion's shell:
//  - TypeScript, and the injected CSS is scoped (`.tp-flex`, `.tp-stroke`)
//    instead of claiming global `.flex` / `.stroke` class names.
//  - The variable font (Roboto Flex, wght + wdth axes) is bundled with the
//    app via @fontsource-variable rather than fetched from Google Fonts, so
//    the effect works offline too. Passing `fontUrl` still loads a remote
//    font once through a <link> in <head>, instead of an @import per instance.
//  - `maxFontSize`, and a fit-to-width pass, so a heading can never push the
//    page into horizontal scroll on a narrow phone.
//  - Honours Orion's Reduce Motion switch (html.reduce-motion): the letters
//    settle into a static weight and the animation loop never starts.
//  - The per-frame loop only touches the DOM while the pointer is still
//    easing towards its target, so an idle heading costs nothing on mobile.
//  - Screen readers get the whole phrase once (aria-label), not letter by letter.

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import '@fontsource-variable/roboto-flex/wdth.css'

const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return Math.sqrt(dx * dx + dy * dy)
}

const getAttr = (distance: number, maxDist: number, minVal: number, maxVal: number) => {
  const val = maxVal - Math.abs((maxVal * distance) / maxDist)
  return Math.max(minVal, val + minVal)
}

function debounce<A extends unknown[]>(fn: (...args: A) => void, delay: number) {
  let t: number | undefined
  return (...args: A) => {
    window.clearTimeout(t)
    t = window.setTimeout(() => fn(...args), delay)
  }
}

function ensureFontLink(href?: string) {
  if (!href || typeof document === 'undefined') return
  if (document.head.querySelector(`link[data-tp-font="${href}"]`)) return
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = href
  link.dataset.tpFont = href
  document.head.appendChild(link)
}

const reducedMotion = () =>
  typeof document !== 'undefined' && document.documentElement.classList.contains('reduce-motion')

export interface TextPressureProps {
  text?: string
  fontFamily?: string
  fontUrl?: string
  width?: boolean
  weight?: boolean
  italic?: boolean
  alpha?: boolean
  flex?: boolean
  stroke?: boolean
  scale?: boolean
  textColor?: string
  strokeColor?: string
  className?: string
  minFontSize?: number
  /** Orion addition: upper bound on the computed size. */
  maxFontSize?: number
  /** Orion addition: heading level to render. */
  as?: 'h1' | 'h2' | 'div'
  style?: CSSProperties
}

export default function TextPressure({
  text = 'Compressa',
  fontFamily = "'Roboto Flex Variable', 'Roboto Flex', 'Sora', system-ui, sans-serif",
  fontUrl,

  width = true,
  weight = true,
  italic = true,
  alpha = false,

  flex = true,
  stroke = false,
  scale = false,

  textColor = '#FFFFFF',
  strokeColor = '#FF0000',
  className = '',

  minFontSize = 24,
  maxFontSize = Infinity,
  as: Tag = 'h1',
  style,
}: TextPressureProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const titleRef = useRef<HTMLElement | null>(null)
  const spansRef = useRef<(HTMLSpanElement | null)[]>([])

  const mouseRef = useRef({ x: 0, y: 0 })
  const cursorRef = useRef({ x: 0, y: 0 })
  const dirtyRef = useRef(true)
  /** Shrink factor applied on top of the computed size. The letters widen and
   * narrow as the pointer moves, so the fit is re-checked every frame; it only
   * ever shrinks between resizes, so the heading can't pulse. */
  const fitRef = useRef(1)

  /** Set the heading size directly, and size the (layout-contained) box to
   * match, so a size change never has to wait for a React render. */
  const applyFont = useCallback((px: number) => {
    const t = titleRef.current
    const c = containerRef.current
    if (t) t.style.fontSize = `${px}px`
    if (c && !scale) c.style.height = `${px}px`
  }, [scale])

  const [fontSize, setFontSize] = useState(minFontSize)
  const fontSizeRef = useRef(minFontSize)
  fontSizeRef.current = fontSize
  const [scaleY, setScaleY] = useState(1)
  const [lineHeight, setLineHeight] = useState(1)

  // A space inside an inline-block collapses to nothing; keep word gaps.
  const chars = useMemo(() => text.split('').map((c) => (c === ' ' ? '\u00A0' : c)), [text])
  spansRef.current.length = chars.length

  useEffect(() => { ensureFontLink(fontUrl) }, [fontUrl])

  useEffect(() => {
    const onMove = (x: number, y: number) => {
      cursorRef.current.x = x
      cursorRef.current.y = y
      dirtyRef.current = true
    }
    const handleMouseMove = (e: MouseEvent) => onMove(e.clientX, e.clientY)
    const handleTouchMove = (e: TouchEvent) => {
      const t = e.touches[0]
      if (t) onMove(t.clientX, t.clientY)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('touchmove', handleTouchMove, { passive: true })

    if (containerRef.current) {
      const { left, top, width: w, height: h } = containerRef.current.getBoundingClientRect()
      mouseRef.current.x = left + w / 2
      mouseRef.current.y = top + h / 2
      cursorRef.current.x = mouseRef.current.x
      cursorRef.current.y = mouseRef.current.y
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('touchmove', handleTouchMove)
    }
  }, [])

  /** Never let the heading exceed its container (no horizontal page scroll).
   * Applied straight to the element's style: cheap, and no re-render loop. */
  const fitToWidth = useCallback(() => {
    const container = containerRef.current
    const t = titleRef.current
    if (!container || !t) return
    const avail = container.clientWidth
    const need = t.scrollWidth
    if (avail > 0 && need > avail + 0.5) {
      fitRef.current = Math.max(0.3, fitRef.current * (avail / need) * 0.98)
      applyFont(fontSizeRef.current * fitRef.current)
    }
  }, [applyFont])

  const setSize = useCallback(() => {
    const container = containerRef.current
    const title = titleRef.current
    if (!container || !title) return

    const { width: containerW, height: containerH } = container.getBoundingClientRect()
    if (containerW <= 0) return

    let next = containerW / (chars.length / 2)
    next = Math.min(maxFontSize, Math.max(next, minFontSize))

    fitRef.current = 1
    fontSizeRef.current = next
    // Set directly too: if `next` equals the current state React skips the
    // re-render, and the fitted size from before would otherwise stick.
    applyFont(next)
    setFontSize(next)
    setScaleY(1)
    setLineHeight(1)
    dirtyRef.current = true

    requestAnimationFrame(() => {
      const t = titleRef.current
      if (!t) return
      fitToWidth()
      const textRect = t.getBoundingClientRect()
      if (scale && textRect.height > 0) {
        const yRatio = containerH / textRect.height
        setScaleY(yRatio)
        setLineHeight(yRatio)
      }
    })
  }, [chars.length, minFontSize, maxFontSize, scale, fitToWidth, applyFont])

  useEffect(() => {
    const debouncedSetSize = debounce(setSize, 100)
    debouncedSetSize()
    // Re-measure once the variable font has actually arrived.
    document.fonts?.ready.then(() => debouncedSetSize()).catch(() => {})
    const ro = new ResizeObserver(() => debouncedSetSize())
    if (containerRef.current) ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [setSize])

  useEffect(() => {
    if (reducedMotion()) {
      spansRef.current.forEach((span) => {
        if (span) span.style.fontVariationSettings = `'wght' ${weight ? 600 : 400}, 'wdth' 100, 'ital' 0`
      })
      fitToWidth()
      return
    }

    let rafId = 0
    let last = 0
    const animate = (ts: number) => {
      rafId = requestAnimationFrame(animate)
      const m = mouseRef.current
      const c = cursorRef.current
      // Frame-rate independent easing. The upstream `/15` per frame lagged
      // badly whenever a frame ran long; this closes ~22% of the gap per
      // 16.7ms regardless of how long the frame actually took.
      const dt = last ? Math.min(64, ts - last) : 16.7
      last = ts
      const k = 1 - Math.pow(1 - 0.22, dt / 16.7)
      m.x += (c.x - m.x) * k
      m.y += (c.y - m.y) * k
      const settling = Math.abs(c.x - m.x) > 0.3 || Math.abs(c.y - m.y) > 0.3

      const title = titleRef.current
      const container = containerRef.current
      if (!title || !container || !(settling || dirtyRef.current)) return
      dirtyRef.current = false

      // READ everything first, then WRITE. Measuring a span straight after
      // changing the previous span's width axis forces a full layout per
      // letter — that per-letter reflow is what made the heading lag.
      // Batched, the browser lays the text out once per frame.
      const spans = spansRef.current
      const titleRect = title.getBoundingClientRect()
      const availW = container.clientWidth
      let contentW = 0
      const centers = spans.map((span) => {
        if (!span) return null
        const r = span.getBoundingClientRect()
        contentW += r.width
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
      })

      const maxDist = Math.max(1, titleRect.width / 2)
      for (let i = 0; i < spans.length; i++) {
        const span = spans[i]
        const ctr = centers[i]
        if (!span || !ctr) continue
        const d = dist(m, ctr)
        // Quantised axis values. Every distinct (wght, wdth) pair makes the
        // browser build a new instance of the variable font — ~30ms each on a
        // mid-range laptop, which is what made the heading trail the pointer.
        // On a small fixed grid the instances are built once and then reused
        // from cache (~2ms a frame); at these sizes the steps are invisible.
        const wdth = width ? Math.min(200, 5 + Math.round((getAttr(d, maxDist, 5, 200) - 5) / 8) * 8) : 100
        const wght = weight ? Math.min(900, 100 + Math.round((getAttr(d, maxDist, 100, 900) - 100) / 25) * 25) : 400
        const italVal = italic ? (Math.round(getAttr(d, maxDist, 0, 1) * 10) / 10).toFixed(1) : '0'
        const settings = `'wght' ${wght}, 'wdth' ${wdth}, 'ital' ${italVal}`
        if (span.style.fontVariationSettings !== settings) span.style.fontVariationSettings = settings
        if (alpha) {
          const alphaVal = getAttr(d, maxDist, 0, 1).toFixed(2)
          if (span.style.opacity !== alphaVal) span.style.opacity = alphaVal
        }
      }

      // Fit check from the measurement already taken — no extra layout.
      // (The title box is always 100% wide; the letters' own widths are what
      // can overflow it.)
      if (availW > 0 && contentW > availW + 0.5) {
        fitRef.current = Math.max(0.3, fitRef.current * (availW / contentW) * 0.98)
        applyFont(fontSizeRef.current * fitRef.current)
      }
    }

    rafId = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafId)
  }, [width, weight, italic, alpha, fitToWidth, applyFont])

  const styleElement = useMemo(
    () => (
      <style>{`
        .tp-flex { display: flex; justify-content: space-between; }
        .tp-stroke span { position: relative; color: ${textColor}; }
        .tp-stroke span::after {
          content: attr(data-char);
          position: absolute; left: 0; top: 0;
          color: transparent; z-index: -1;
          -webkit-text-stroke-width: 3px;
          -webkit-text-stroke-color: ${strokeColor};
        }
        .text-pressure-title { color: ${textColor}; }
      `}</style>
    ),
    [textColor, strokeColor],
  )

  const dynamicClassName = [className, flex ? 'tp-flex' : '', stroke ? 'tp-stroke' : ''].filter(Boolean).join(' ')

  return (
    <div
      ref={containerRef}
      className="text-pressure"
      style={{
        position: 'relative', width: '100%', background: 'transparent',
        // The letters change width every frame. Containing layout (with an
        // explicit height = one line) makes this box a layout root, so each
        // frame re-lays out one line of text instead of the whole page.
        height: scale ? '100%' : fontSize * fitRef.current,
        contain: scale ? undefined : 'layout size style',
        ...style,
      }}
    >
      {styleElement}
      <Tag
        ref={titleRef as never}
        aria-label={text}
        className={`text-pressure-title ${dynamicClassName}`}
        style={{
          fontFamily,
          textTransform: 'uppercase',
          fontSize: fontSize * fitRef.current,
          lineHeight,
          transform: `scale(1, ${scaleY})`,
          transformOrigin: 'center top',
          margin: 0,
          textAlign: 'center',
          userSelect: 'none',
          whiteSpace: 'nowrap',
          fontWeight: 100,
          letterSpacing: 0,
          width: '100%',
        }}
      >
        {chars.map((char, i) => (
          <span
            key={i}
            aria-hidden="true"
            ref={(el) => { spansRef.current[i] = el }}
            data-char={char}
            style={{ display: 'inline-block', color: stroke ? undefined : textColor }}
          >
            {char}
          </span>
        ))}
      </Tag>
    </div>
  )
}
