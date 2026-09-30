import moonBrandmarkUrl from '../assets/brandmark-moon.png'

import { useId } from 'react'

/* ------------------------------------------------------------------ geometry
   Every icon is two layers on a 24px grid:
   - LINE:   the outline — rounded caps and joins, one stroke weight, which
             carries the meaning and the semantic colour (ok / warn / danger).
   - VOLUME: a soft translucent shape set just behind and up-right of the
             line, filled with Orion's cobalt → light-blue gradient. It gives
             the slight 2.5D depth without ever carrying meaning on its own.
   Every glyph has one, so no icon renders as plain monochrome line-art. */

const circle = (cx: number, cy: number, r: number) =>
  `M${cx} ${cy - r}a${r} ${r} 0 1 1 0 ${2 * r}a${r} ${r} 0 1 1 0-${2 * r}z`
const rr = (x: number, y: number, w: number, h: number, r: number) =>
  `M${x + r} ${y}h${w - 2 * r}a${r} ${r} 0 0 1 ${r} ${r}v${h - 2 * r}a${r} ${r} 0 0 1-${r} ${r}h-${w - 2 * r}a${r} ${r} 0 0 1-${r}-${r}v-${h - 2 * r}a${r} ${r} 0 0 1 ${r}-${r}z`

const P: Record<string, string> = {
  plus: 'M12 5v14M5 12h14',
  mic: 'M12 3a3 3 0 0 1 3 3v5.5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6',
  arrowup: 'M12 19V5M5 12l7-7 7 7',
  chat: 'M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4z',
  home: 'M3.8 11 12 4l8.2 7M6 9.6v8.9A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V9.6M10 20v-5h4v5',
  user: 'M12 5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7M5 20a7 7 0 0 1 14 0',
  info: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M12 11v5M12 8h.01',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5',
  folder: 'M4 7a2 2 0 0 1 2-2h3.6l1.8 2H18a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z',
  search: 'M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12M20 20l-4.2-4.2',
  cam: 'M3 8a2 2 0 0 1 2-2h2.2l1.2-2h7.2l1.2 2H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12.5 8.9a3.6 3.6 0 1 1 0 7.2 3.6 3.6 0 0 1 0-7.2',
  square: 'M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z',
  dots: 'M5 10.7a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6M12 10.7a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6M19 10.7a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6',
  trash: 'M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13',
  pencil: 'M4 20l1-4L16 5l3 3L8 19z',
  archive: 'M4 4h16v4H4zM5 8v11h14V8M10 12h4',
  chevL: 'M14 6l-6 6 6 6',
  chevR: 'M10 6l6 6-6 6',
  chevD: 'M6 10l6 6 6-6',
  x: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7',
  warn: 'M12 4.5 2.8 20h18.4zM12 10v4.5M12 17.5h.01',
  shield: 'M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6zM9 12l2.2 2.2L15.2 10',
  zoomin: 'M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12M20 20l-4.2-4.2M11 8.5v5M8.5 11h5',
  zoomout: 'M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12M20 20l-4.2-4.2M8.5 11h5',
  dl: 'M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14',
  print: 'M7 9V4h10v5M7 18H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2M7 14h10v6H7z',
  sparks: 'M12 3.5 13.7 9l5.5 1.7-5.5 1.7L12 18l-1.7-5.6L4.8 10.7 10.3 9z',
  book: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5zM4 18.5V5.5',
  gauge: 'M5 17a8 8 0 1 1 14 0M12 13.5 16 9.5',
  pin: 'M12 21s6.5-6.1 6.5-10.4a6.5 6.5 0 0 0-13 0C5.5 14.9 12 21 12 21zM12 8.2a2.2 2.2 0 1 1 0 4.4 2.2 2.2 0 0 1 0-4.4',
  wifi: 'M3.5 9.5a13 13 0 0 1 17 0M6.8 13a8.4 8.4 0 0 1 10.4 0M10 16.4a3.6 3.6 0 0 1 4 0M12 19.8h.01',
  wifioff: 'M3.5 9.5a13 13 0 0 1 6-3.3M14.5 6.3a13 13 0 0 1 6 3.2M6.8 13a8.4 8.4 0 0 1 3-2M10 16.4a3.6 3.6 0 0 1 4 0M12 19.8h.01M3 3l18 18',
  cpu: 'M9 7h6a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
  layers: 'M12 3 3 8l9 5 9-5zM3 13l9 5 9-5',
  clock: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M12 7.5V12l3 2',
  history: 'M4 12a8 8 0 1 0 2.6-5.9L4 8.5M4 4v4.5h4.5M12 8v4.3l3 1.8',
  eye: 'M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6zM12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6',
  sun: 'M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4',
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z',
  target: 'M12 4a8 8 0 1 1 0 16 8 8 0 0 1 0-16M12 8.8a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4M12 1.8v3.4M12 18.8v3.4M1.8 12h3.4M18.8 12h3.4',
  ruler: 'M3 9.5h18v5H3zM7 9.5v2.4M11 9.5v3.2M15 9.5v2.4M19 9.5v3.2',
  text: 'M5 6h14M5 12h10M5 18h7',
  stop: 'M9 7h6a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z',
  refresh: 'M20 11a8 8 0 1 0-1.3 5.5M20 4.5V11h-6.4',
  lock: 'M7.4 10.5h9.2a2.4 2.4 0 0 1 2.4 2.4v5.2a2.4 2.4 0 0 1-2.4 2.4H7.4A2.4 2.4 0 0 1 5 18.1v-5.2a2.4 2.4 0 0 1 2.4-2.4zM8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5',
  menu: 'M4 7h16M4 12h16M4 17h16',
  panel: 'M5.9 4.5h12.2a2.4 2.4 0 0 1 2.4 2.4v10.2a2.4 2.4 0 0 1-2.4 2.4H5.9a2.4 2.4 0 0 1-2.4-2.4V6.9a2.4 2.4 0 0 1 2.4-2.4zM10 4.5v15',
  grid: 'M5.5 4h3.5a1.5 1.5 0 0 1 1.5 1.5V9a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 9V5.5A1.5 1.5 0 0 1 5.5 4zM15 4h3.5A1.5 1.5 0 0 1 20 5.5V9a1.5 1.5 0 0 1-1.5 1.5H15A1.5 1.5 0 0 1 13.5 9V5.5A1.5 1.5 0 0 1 15 4zM5.5 13.5H9a1.5 1.5 0 0 1 1.5 1.5v3.5A1.5 1.5 0 0 1 9 20H5.5A1.5 1.5 0 0 1 4 18.5V15a1.5 1.5 0 0 1 1.5-1.5zM15 13.5h3.5A1.5 1.5 0 0 1 20 15v3.5A1.5 1.5 0 0 1 18.5 20H15a1.5 1.5 0 0 1-1.5-1.5V15a1.5 1.5 0 0 1 1.5-1.5z',
  // Names the app already uses (work-trail steps, the reasoning mark) that had
  // no glyph and silently fell back to "info".
  spark: 'M12 3.5 13.7 9l5.5 1.7-5.5 1.7L12 18l-1.7-5.6L4.8 10.7 10.3 9z',
  type: 'M6 6.5h12M12 6.5v12M9.5 18.5h5',
  globe: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M3.5 12h17M12 3.5c2.4 2.5 3.6 5.3 3.6 8.5s-1.2 6-3.6 8.5c-2.4-2.5-3.6-5.3-3.6-8.5s1.2-6 3.6-8.5',
  help: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M9.6 9.6a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1.9-1.1 1.6v.4M12 16.8h.01',
  google: 'M21 12.2c0-.7-.06-1.3-.18-1.9H12v3.6h5.05a4.3 4.3 0 0 1-1.87 2.8v2.3h3.02C19.96 17.4 21 15 21 12.2z',
}


/* The volume layer. Omitted names get none. */
const V: Record<string, string> = {
  mic: rr(10.5, 2, 6, 11, 3),
  chat: rr(7, 2.5, 14.5, 10, 2.5),
  home: 'M8 9.2 13.5 4.6 19 9.2V17H8z',
  user: circle(13.3, 7.2, 3.8) + 'M7.2 19.5a6.5 6.5 0 0 1 13 0z',
  info: circle(13.2, 10.8, 7.4),
  file: rr(7, 2, 12, 15.5, 2.2),
  folder: rr(6.5, 6.5, 15, 11, 2.5),
  search: circle(12.2, 9.8, 5.2),
  cam: rr(5, 5.5, 17, 11.5, 2.5),
  square: rr(6, 3, 15, 15, 3.5),
  dots: rr(3.5, 7.5, 18, 8, 4),
  trash: rr(8.5, 6, 10, 13, 2),
  pencil: 'M15.8 3.2 20.8 8.2 12 17 7 12z',
  archive: rr(6, 3, 15, 5.5, 1.6),
  check: rr(8, 4.5, 12.5, 12.5, 3.5),
  // Thin glyphs: a small accent disc beside the strokes (never under them),
  // so a 14px plus / send arrow stays perfectly legible.
  plus: circle(16.2, 6.4, 3),
  arrowup: circle(16.8, 8.2, 3),
  x: circle(16.6, 10.6, 2.8),
  menu: circle(18, 4.6, 2.6),
  chevL: circle(15.4, 10.6, 2.8),
  chevR: circle(7, 10.6, 2.8),
  chevD: circle(10.6, 6.6, 2.8),
  warn: 'M13 6.3 20.6 19.2H5.4z',
  shield: 'M12 3l7 3v6c0 4.2-2.9 7.6-7 9z',
  zoomin: circle(12.2, 9.8, 5.2),
  zoomout: circle(12.2, 9.8, 5.2),
  dl: rr(6.5, 13.5, 14, 6.5, 2),
  print: rr(6, 9, 16, 8, 2),
  sparks: circle(14, 10, 5.8),
  spark: circle(14, 10, 5.8),
  book: rr(7.5, 2, 12.5, 15, 2),
  gauge: 'M6.5 16a7 7 0 1 1 14 0z',
  pin: circle(13.5, 9, 5),
  wifi: circle(14, 10, 5.2),
  wifioff: circle(14, 10, 5.2),
  cpu: rr(8.5, 5.5, 10.5, 10.5, 2),
  layers: 'M13.4 2.6 21.4 7 13.4 11.4 5.4 7z',
  clock: circle(13.2, 10.8, 7.2),
  history: circle(13.2, 10.8, 6.8),
  eye: circle(13, 10.6, 5),
  sun: circle(13, 11, 4.6),
  moon: 'M21 13.5A8 8 0 0 1 11 3.8a8 8 0 1 0 10 9.7z',
  target: circle(13, 11, 5.4),
  ruler: rr(4.5, 7.5, 17.5, 5.5, 1.5),
  text: rr(6.5, 3.5, 14, 9, 2),
  type: rr(8, 3.5, 12, 9, 2),
  stop: rr(7, 7, 10, 10, 2),
  refresh: circle(13.2, 10.8, 6.4),
  lock: rr(6.5, 9, 13, 10, 2.4),
  panel: 'M5.9 4.5H10v15H5.9a2.4 2.4 0 0 1-2.4-2.4V6.9a2.4 2.4 0 0 1 2.4-2.4z',
  grid: rr(13.5, 4, 6.5, 6.5, 1.5),
  globe: circle(13.2, 10.8, 7.2),
  help: circle(13.2, 10.8, 7.2),
}

/* A stop square is filled, so it never reads as the outlined "capture frame"
   square next to it. It takes the line colour, like a record/stop control. */
const SOLID = new Set(['stop'])

/* A status colour (ok / warn / danger / record) tints the volume in that same
   colour, so success, caution and recording never turn blue. */
const STATUS = /ok|warn|danger|record|#43d9a3|#f5b942|#ff7a6b|#e5484d|#0b7a52/i

export type IconName = keyof typeof P | string

export function Icon({
  name, size = 18, stroke = 'currentColor', width = 1.7, className,
}: {
  name: IconName
  size?: number
  stroke?: string
  width?: number
  className?: string
}) {
  const d = P[name] ?? P.info
  const v = V[name]
  const gid = `vfi${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const solid = SOLID.has(name)
  const status = STATUS.test(stroke)
  // A neutral line (white/grey text colours) is tinted toward Orion's icon blue,
  // keeping its relative brightness, so icons read as blue line-art rather than
  // plain monochrome. Status colours and the dark-on-white active state keep
  // their exact colour.
  const neutral = !status && !/on-invert/.test(stroke)
  const line = neutral ? `color-mix(in srgb, ${stroke} 58%, var(--vf-icon-line))` : stroke
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
      className={className ? `vf-icon ${className}` : 'vf-icon'} style={{ flex: 'none' }}
    >
      {v && !solid && (
        <defs>
          <linearGradient id={gid} x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" style={{ stopColor: status ? stroke : 'var(--vf-icon-a)', stopOpacity: status ? 0.42 : 'var(--vf-icon-a-alpha)' }} />
            <stop offset="1" style={{ stopColor: status ? stroke : 'var(--vf-icon-b)', stopOpacity: status ? 0.1 : 'var(--vf-icon-b-alpha)' }} />
          </linearGradient>
        </defs>
      )}
      {v && (
        <path
          d={v} fill={solid ? stroke : `url(#${gid})`} opacity={solid ? 0.42 : undefined}
          transform={solid ? undefined : 'translate(1.3 -1.3)'}
        />
      )}
      <path d={d} style={{ stroke: line }} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Brandmark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true" style={{ flex: 'none' }}>
      <path d="M16 2.6 28 9.3v13.4L16 29.4 4 22.7V9.3z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" opacity=".85" />
      <path d="M11.4 11.4V9h-2.2M20.6 11.4V9h2.2M11.4 20.6V23h-2.2M20.6 20.6V23h2.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="16" cy="16" r="4.4" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="16" cy="16" r="1.5" fill="currentColor" />
    </svg>
  )
}

/** Orion's mark: a crescent moon, pitted with craters. This is the app's
 * actual logo — used top-left in the nav and wherever the brand needs to
 * read at a glance. It's a supplied image asset (fine linework a hand-coded
 * SVG can't reproduce faithfully) rather than a redrawn approximation. */
export function MoonMark({ size = 32 }: { size?: number }) {
  return (
    <img
      src={moonBrandmarkUrl}
      className="vf-moon"
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      style={{ flex: 'none', display: 'block', objectFit: 'contain' }}
    />
  )
}

export function AiMark({ size = 34 }: { size?: number }) {
  return (
    <span className="aimark" style={{ width: size, height: size }}>
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="6.6" stroke="var(--vf-text)" strokeWidth="1.5" />
        <circle cx="12" cy="12" r="2" fill="var(--vf-text)" />
        <path d="M12 2.6v2.6M12 18.8v2.6M2.6 12h2.6M18.8 12h2.6" stroke="var(--vf-muted)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </span>
  )
}
