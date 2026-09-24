const P: Record<string, string> = {
  plus: 'M12 5v14M5 12h14',
  mic: 'M9 3h6v11a3 3 0 0 1-6 0zM5 11a7 7 0 0 0 14 0M12 18v3',
  arrowup: 'M12 19V5M5 12l7-7 7 7',
  chat: 'M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4z',
  home: 'M4 11l8-7 8 7M6 10v9h12v-9',
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
  shield: 'M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z',
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
  stop: 'M8.5 6.5h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z',
  refresh: 'M20 11a8 8 0 1 0-1.3 5.5M20 4.5V11h-6.4',
  lock: 'M7.4 10.5h9.2a2.4 2.4 0 0 1 2.4 2.4v5.2a2.4 2.4 0 0 1-2.4 2.4H7.4A2.4 2.4 0 0 1 5 18.1v-5.2a2.4 2.4 0 0 1 2.4-2.4zM8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5',
  menu: 'M4 7h16M4 12h16M4 17h16',
  panel: 'M5.9 4.5h12.2a2.4 2.4 0 0 1 2.4 2.4v10.2a2.4 2.4 0 0 1-2.4 2.4H5.9a2.4 2.4 0 0 1-2.4-2.4V6.9a2.4 2.4 0 0 1 2.4-2.4zM10 4.5v15',
  grid: 'M5.5 4h3.5a1.5 1.5 0 0 1 1.5 1.5V9a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 9V5.5A1.5 1.5 0 0 1 5.5 4zM15 4h3.5A1.5 1.5 0 0 1 20 5.5V9a1.5 1.5 0 0 1-1.5 1.5H15A1.5 1.5 0 0 1 13.5 9V5.5A1.5 1.5 0 0 1 15 4zM5.5 13.5H9a1.5 1.5 0 0 1 1.5 1.5v3.5A1.5 1.5 0 0 1 9 20H5.5A1.5 1.5 0 0 1 4 18.5V15a1.5 1.5 0 0 1 1.5-1.5zM15 13.5h3.5A1.5 1.5 0 0 1 20 15v3.5A1.5 1.5 0 0 1 18.5 20H15a1.5 1.5 0 0 1-1.5-1.5V15a1.5 1.5 0 0 1 1.5-1.5z',
  google: 'M21 12.2c0-.7-.06-1.3-.18-1.9H12v3.6h5.05a4.3 4.3 0 0 1-1.87 2.8v2.3h3.02C19.96 17.4 21 15 21 12.2z',
}

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
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
      className={className} style={{ flex: 'none' }}
    >
      <path d={d} stroke={stroke} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" />
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
