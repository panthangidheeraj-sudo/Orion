import moonBrandmarkUrl from '../assets/brandmark-moon.png'

/* ------------------------------------------------------------------ geometry
   One monochrome line-art language on a 24px grid: orbital rings, radar and
   crosshair geometry, crescents and star points, technical/observatory shapes.
   Rounded caps and joins, one stroke weight per use. Nothing is filled or
   tinted; colour only ever comes from the caller (text tokens or a status). */

const P: Record<string, string> = {
  settings: 'M12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6M12 5.7a6.3 6.3 0 1 1 0 12.6 6.3 6.3 0 0 1 0-12.6M18.30 12.00L21.60 12.00M16.45 16.45L18.79 18.79M12.00 18.30L12.00 21.60M7.55 16.45L5.21 18.79M5.70 12.00L2.40 12.00M7.55 7.55L5.21 5.21M12.00 5.70L12.00 2.40M16.45 7.55L18.79 5.21',
  upload: 'M12 15V4M7.8 8.2 12 4l4.2 4.2M4.5 15.5a7.5 5.5 0 0 0 15 0',
  plus: 'M12 4.8v14.4M4.8 12h14.4',
  mic: 'M12 3a3 3 0 0 1 3 3v5.5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.8 21h6.4',
  arrowup: 'M12 19.5V5M5.8 11.2 12 5l6.2 6.2',
  chat: 'M12 3.8a8.2 8.2 0 1 1-3.6 15.6L4.2 20.4l1.1-4A8.2 8.2 0 0 1 12 3.8M8.3 12h.01M12 12h.01M15.7 12h.01',
  home: 'M3 20h18M5 20v-7.5a7 7 0 0 1 14 0V20M10 20v-3.6a2 2 0 0 1 4 0V20M12 5.5V9',
  user: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M12 7.6a2.9 2.9 0 1 1 0 5.8 2.9 2.9 0 0 1 0-5.8M6.6 18.2a6.4 5 0 0 1 10.8 0',
  info: 'M12 3.6a8.4 8.4 0 1 1 0 16.8 8.4 8.4 0 0 1 0-16.8M12 11v5.2M12 7.8h.01',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5',
  folder: 'M4 7a2 2 0 0 1 2-2h3.6l1.8 2H18a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z',
  search: 'M10.8 4.6a6.2 6.2 0 1 1 0 12.4 6.2 6.2 0 0 1 0-12.4M20 20l-4.8-4.8M8 10.6a3 3 0 0 1 2.6-2.6',
  cam: 'M3.5 8.2A2 2 0 0 1 5.5 6.2h2.1l1.3-2h6.2l1.3 2h2.1a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2zM12 9.4a3.7 3.7 0 1 1 0 7.4 3.7 3.7 0 0 1 0-7.4M12 12.4a.7.7 0 1 1 0 1.4.7.7 0 0 1 0-1.4',
  square: 'M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z',
  dots: 'M5 10.7a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6M12 10.7a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6M19 10.7a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6',
  trash: 'M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13',
  pencil: 'M4 20l1-4L16 5l3 3L8 19z',
  archive: 'M4 4h16v4H4zM5 8v11h14V8M10 12h4',
  chevL: 'M14 6l-6 6 6 6',
  chevR: 'M10 6l6 6-6 6',
  chevD: 'M6 10l6 6 6-6',
  x: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.6l4.6 4.6L19 7.4',
  warn: 'M12 4 3 19.6h18zM12 9.8v4.4M12 17h.01',
  shield: 'M12 3.2l7 2.8v6c0 4.3-2.9 7.6-7 9-4.1-1.4-7-4.7-7-9V6zM8.8 12l2.3 2.3 4.1-4.4',
  zoomin: 'M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12M20 20l-4.2-4.2M11 8.5v5M8.5 11h5',
  zoomout: 'M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12M20 20l-4.2-4.2M8.5 11h5',
  dl: 'M12 4v11M7.8 11l4.2 4.2 4.2-4.2M4.5 15.5a7.5 5.5 0 0 0 15 0',
  print: 'M7 9V4h10v5M7 18H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2M7 14h10v6H7z',
  sparks: 'M12 3 13.9 9.1 20 11l-6.1 1.9L12 19l-1.9-6.1L4 11l6.1-1.9z',
  book: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5zM4 18.5V5.5',
  gauge: 'M5 17a8 8 0 1 1 14 0M12 13.5 16 9.5',
  pin: 'M12 21s6.5-6.1 6.5-10.4a6.5 6.5 0 0 0-13 0C5.5 14.9 12 21 12 21zM12 8.2a2.2 2.2 0 1 1 0 4.4 2.2 2.2 0 0 1 0-4.4',
  wifi: 'M3.5 9.5a13 13 0 0 1 17 0M6.8 13a8.4 8.4 0 0 1 10.4 0M10 16.4a3.6 3.6 0 0 1 4 0M12 19.8h.01',
  wifioff: 'M3.5 9.5a13 13 0 0 1 6-3.3M14.5 6.3a13 13 0 0 1 6 3.2M6.8 13a8.4 8.4 0 0 1 3-2M10 16.4a3.6 3.6 0 0 1 4 0M12 19.8h.01M3 3l18 18',
  cpu: 'M9 7h6a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
  layers: 'M12 3 3 8l9 5 9-5zM3 13l9 5 9-5',
  clock: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M12 7.5V12l3 2',
  history: 'M4.2 12a7.8 7.8 0 1 0 2.4-5.6L4.2 8.8M4.2 4.2v4.6h4.6M12 7.8V12l3 1.8',
  eye: 'M2.5 12S6 6.2 12 6.2 21.5 12 21.5 12 18 17.8 12 17.8 2.5 12 2.5 12zM12 8.9a3.1 3.1 0 1 1 0 6.2 3.1 3.1 0 0 1 0-6.2M12 11.4a.6.6 0 1 1 0 1.2.6.6 0 0 1 0-1.2',
  sun: 'M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4',
  moon: 'M19.5 14.6A8.2 8.2 0 0 1 9.4 4.5a8.2 8.2 0 1 0 10.1 10.1zM17 4v3M15.5 5.5h3',
  target: 'M12 4.6a7.4 7.4 0 1 1 0 14.8 7.4 7.4 0 0 1 0-14.8M12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6M12 2v3.2M12 18.8V22M2 12h3.2M18.8 12H22',
  ruler: 'M3 9.5h18v5H3zM7 9.5v2.4M11 9.5v3.2M15 9.5v2.4M19 9.5v3.2',
  text: 'M5 6h14M5 12h10M5 18h7',
  stop: 'M8 6.5h8A1.5 1.5 0 0 1 17.5 8v8a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 16V8A1.5 1.5 0 0 1 8 6.5z',
  refresh: 'M20 11a8 8 0 1 0-1.3 5.5M20 4.5V11h-6.4',
  lock: 'M7.4 10.5h9.2a2.4 2.4 0 0 1 2.4 2.4v5.2a2.4 2.4 0 0 1-2.4 2.4H7.4A2.4 2.4 0 0 1 5 18.1v-5.2a2.4 2.4 0 0 1 2.4-2.4zM8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5',
  menu: 'M4 7h16M4 12h16M4 17h16',
  panel: 'M5.9 4.5h12.2a2.4 2.4 0 0 1 2.4 2.4v10.2a2.4 2.4 0 0 1-2.4 2.4H5.9a2.4 2.4 0 0 1-2.4-2.4V6.9a2.4 2.4 0 0 1 2.4-2.4zM10 4.5v15',
  grid: 'M5.5 4h3.5a1.5 1.5 0 0 1 1.5 1.5V9a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 9V5.5A1.5 1.5 0 0 1 5.5 4zM15 4h3.5A1.5 1.5 0 0 1 20 5.5V9a1.5 1.5 0 0 1-1.5 1.5H15A1.5 1.5 0 0 1 13.5 9V5.5A1.5 1.5 0 0 1 15 4zM5.5 13.5H9a1.5 1.5 0 0 1 1.5 1.5v3.5A1.5 1.5 0 0 1 9 20H5.5A1.5 1.5 0 0 1 4 18.5V15a1.5 1.5 0 0 1 1.5-1.5zM15 13.5h3.5A1.5 1.5 0 0 1 20 15v3.5A1.5 1.5 0 0 1 18.5 20H15a1.5 1.5 0 0 1-1.5-1.5V15a1.5 1.5 0 0 1 1.5-1.5z',
  // Names the app already uses (work-trail steps, the reasoning mark) that had
  // no glyph and silently fell back to "info".
  spark: 'M12 3 13.9 9.1 20 11l-6.1 1.9L12 19l-1.9-6.1L4 11l6.1-1.9z',
  type: 'M6 6.5h12M12 6.5v12M9.5 18.5h5',
  globe: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M3.5 12h17M12 3.5c2.4 2.5 3.6 5.3 3.6 8.5s-1.2 6-3.6 8.5c-2.4-2.5-3.6-5.3-3.6-8.5s1.2-6 3.6-8.5',
  help: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17M9.6 9.6a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1.9-1.1 1.6v.4M12 16.8h.01',
  google: 'M21 12.2c0-.7-.06-1.3-.18-1.9H12v3.6h5.05a4.3 4.3 0 0 1-1.87 2.8v2.3h3.02C19.96 17.4 21 15 21 12.2z',
}


/* A stop square is filled, so it never reads as the outlined "capture frame"
   square next to it. It takes the line colour, like a record/stop control. */
const SOLID = new Set(['stop'])
const ALIAS: Record<string, string> = { send: 'arrowup', cog: 'settings', gear: 'settings', camera: 'cam' }

export type IconName = keyof typeof P | string

/* One icon language everywhere: white / grey / black line-art in the colour
   its caller passes (text tokens, or a status colour where it carries meaning).
   No gradients, no fills except the solid stop control. */
export function Icon({
  name, size = 18, stroke = 'currentColor', width = 1.7, className,
}: {
  name: IconName
  size?: number
  stroke?: string
  width?: number
  className?: string
}) {
  const key = ALIAS[name] ?? name
  const d = P[key] ?? P.info
  const solid = SOLID.has(key)
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
      className={className ? `vf-icon ${className}` : 'vf-icon'} data-icon={key} style={{ flex: 'none' }}
    >
      <path
        d={d} style={{ stroke }} fill={solid ? stroke : 'none'}
        strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"
      />
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
