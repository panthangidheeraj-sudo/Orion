/**
 * Line art for the About page. Monochrome, thin strokes, currentColor —
 * technical drawings rather than illustrations, so they sit in Orion's
 * black/white identity. Everything is plain SVG: no images, no 3D library.
 */

import type { CSSProperties, ReactNode } from 'react'

const line = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.4,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  vectorEffect: 'non-scaling-stroke' as const,
}
const faint = { ...line, strokeOpacity: 0.45 }

function Svg({ vb, children, className, style }: { vb: string; children: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <svg viewBox={vb} className={className} style={style} aria-hidden="true" focusable="false">
      {children}
    </svg>
  )
}

/* ------------------------------------------------ hero floating objects */

export function CameraFrameArt() {
  return (
    <Svg vb="0 0 64 48">
      <path {...line} d="M4 14V6h10M50 6h10v8M60 34v8H50M14 42H4v-8" />
      <rect {...faint} x="20" y="16" width="24" height="16" rx="2" />
      <circle {...line} cx="32" cy="24" r="4" />
    </Svg>
  )
}
export function WaveformArt() {
  return (
    <Svg vb="0 0 80 32">
      <path {...line} d="M2 16h8l3-8 4 16 4-22 4 26 4-18 3 10 3-6 3 4h8l3-5 3 8 3-3h17" />
    </Svg>
  )
}
export function DocPageArt() {
  return (
    <Svg vb="0 0 44 56">
      <path {...line} d="M6 4h22l10 10v38H6z" />
      <path {...line} d="M28 4v10h10" />
      <path {...faint} d="M12 24h20M12 30h20M12 36h14M12 42h18" />
    </Svg>
  )
}
export function GearArt() {
  const teeth = Array.from({ length: 10 }, (_, i) => {
    const a = (i / 10) * Math.PI * 2
    const x1 = 28 + Math.cos(a) * 17, y1 = 28 + Math.sin(a) * 17
    const x2 = 28 + Math.cos(a) * 23, y2 = 28 + Math.sin(a) * 23
    return <path key={i} {...line} d={`M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`} />
  })
  return (
    <Svg vb="0 0 56 56">
      <circle {...line} cx="28" cy="28" r="17" />
      <circle {...faint} cx="28" cy="28" r="7" />
      {teeth}
    </Svg>
  )
}
export function EyeArt() {
  return (
    <Svg vb="0 0 64 36">
      <path {...line} d="M3 18C12 6 22 2 32 2s20 4 29 16C52 30 42 34 32 34S12 30 3 18z" />
      <circle {...line} cx="32" cy="18" r="8" />
      <circle cx="32" cy="18" r="2.6" fill="currentColor" />
    </Svg>
  )
}
export function CircuitArt() {
  return (
    <Svg vb="0 0 72 48">
      <path {...line} d="M2 24h12l4-8 6 16 6-16 4 8h10" />
      <path {...line} d="M44 14v20M50 14v20" />
      <path {...line} d="M50 24h8v-14h12M58 24v14h12" />
      <circle {...faint} cx="70" cy="10" r="1.6" />
      <circle {...faint} cx="70" cy="38" r="1.6" />
    </Svg>
  )
}

/* ----------------------------------------------------------- machines */

/** Induction motor, side elevation: frame with cooling fins, fan cowl,
 * terminal box, shaft and feet. Used large in "The machine is speaking". */
export function MotorArt({ detail = true }: { detail?: boolean }) {
  const fins = Array.from({ length: 11 }, (_, i) => 78 + i * 10)
  return (
    <Svg vb="0 0 260 170">
      {/* frame */}
      <rect {...line} x="66" y="46" width="118" height="80" rx="10" />
      {detail && fins.map((x) => <path key={x} {...faint} d={`M${x} 50v72`} />)}
      {/* drive-end bell + shaft + coupling */}
      <path {...line} d="M66 56c-10 4-14 14-14 30s4 26 14 30" />
      <path {...line} d="M52 80H22M52 92H22" />
      <rect {...line} x="12" y="74" width="12" height="24" rx="2" />
      {/* fan cowl */}
      <path {...line} d="M184 52h26c8 0 12 6 12 14v40c0 8-4 14-12 14h-26" />
      {detail && <path {...faint} d="M194 60v52M202 60v52M210 62v48" />}
      {/* terminal box */}
      <rect {...line} x="102" y="24" width="44" height="22" rx="3" />
      {detail && <path {...faint} d="M110 32h28M110 38h20" />}
      {/* feet */}
      <path {...line} d="M84 126l-6 18h36l-6-18M144 126l-6 18h36l-6-18" />
      <path {...faint} d="M40 146h196" />
    </Svg>
  )
}

export function PumpArt() {
  return (
    <Svg vb="0 0 260 170">
      {/* volute */}
      <path {...line} d="M150 88a38 38 0 1 1-8-24" />
      <path {...line} d="M142 64c10-6 22-6 30 2" />
      <circle {...faint} cx="120" cy="88" r="18" />
      <circle {...line} cx="120" cy="88" r="5" />
      {/* discharge (top) + suction (left) */}
      <path {...line} d="M150 56V22h22v34M146 22h30" />
      <path {...line} d="M82 80H28M82 96H28M28 74v28" />
      {/* bearing frame + motor stub */}
      <path {...line} d="M158 76h28v24h-28M186 70h46v36h-46z" />
      <path {...faint} d="M198 74v28M210 74v28M222 74v28" />
      {/* base */}
      <path {...line} d="M60 132h180M76 126v6M226 126v6M100 124l-4 8M150 124l4 8" />
    </Svg>
  )
}

export function ControlPanelArt() {
  return (
    <Svg vb="0 0 260 170">
      <rect {...line} x="56" y="12" width="148" height="148" rx="6" />
      <rect {...line} x="72" y="28" width="116" height="38" rx="3" />
      <path {...faint} d="M80 40h40M80 50h64M80 58h24" />
      {/* indicator lamps */}
      {[84, 110, 136, 162].map((x) => <circle key={x} {...line} cx={x} cy="84" r="5" />)}
      {/* push buttons */}
      {[84, 110, 136].map((x) => <rect key={x} {...faint} x={x - 8} y="102" width="16" height="12" rx="2" />)}
      {/* e-stop */}
      <circle {...line} cx="168" cy="126" r="14" />
      <circle {...line} cx="168" cy="126" r="7" />
      <path {...faint} d="M76 136h54M76 144h40" />
    </Svg>
  )
}

export function CompressorArt() {
  return (
    <Svg vb="0 0 260 170">
      {/* receiver tank */}
      <path {...line} d="M60 92h140a22 22 0 0 1 0 44H60a22 22 0 0 1 0-44z" />
      <path {...faint} d="M96 92v44M164 92v44" />
      {/* pump head + cylinder fins */}
      <path {...line} d="M86 92V62h52v30" />
      <path {...faint} d="M90 68h44M90 74h44M90 80h44" />
      <path {...line} d="M100 62V48h24v14" />
      {/* motor + belt guard */}
      <rect {...line} x="148" y="60" width="44" height="32" rx="6" />
      <path {...faint} d="M156 64v24M164 64v24M172 64v24" />
      {/* gauge + relief valve */}
      <circle {...line} cx="214" cy="70" r="11" />
      <path {...line} d="M214 70l5-5M214 81v11" />
      <path {...line} d="M60 92v-12h8v12" />
      {/* feet */}
      <path {...line} d="M72 136l-6 14M188 136l6 14M52 150h160" />
    </Svg>
  )
}

export function CabinetArt() {
  return (
    <Svg vb="0 0 260 170">
      <rect {...line} x="76" y="6" width="108" height="158" rx="4" />
      <path {...line} d="M130 6v158" />
      {/* handles */}
      <path {...line} d="M122 74v22M138 74v22" />
      {/* vents */}
      {[26, 32, 38].map((y) => <path key={y} {...faint} d={`M88 ${y}h30M142 ${y}h30`} />)}
      {[140, 146, 152].map((y) => <path key={y} {...faint} d={`M88 ${y}h30M142 ${y}h30`} />)}
      {/* hazard triangle */}
      <path {...line} d="M103 108l12 20H91z" />
      <path {...line} d="M103 114v7M103 124v.5" />
      {/* name plate */}
      <rect {...faint} x="144" y="108" width="28" height="14" rx="1.5" />
    </Svg>
  )
}

/* -------------------------------------------- memory evidence thumbnails */

export function ThumbBearingArt() {
  return (
    <Svg vb="0 0 80 50">
      <circle {...line} cx="40" cy="25" r="18" />
      <circle {...line} cx="40" cy="25" r="9" />
      {Array.from({ length: 8 }, (_, i) => {
        const a = (i / 8) * Math.PI * 2
        return <circle key={i} {...faint} cx={40 + Math.cos(a) * 13.5} cy={25 + Math.sin(a) * 13.5} r="3" />
      })}
    </Svg>
  )
}
export function ThumbSealArt() {
  return (
    <Svg vb="0 0 80 50">
      <path {...line} d="M8 18h64M8 32h64" />
      <rect {...line} x="30" y="12" width="20" height="26" rx="3" />
      <path {...faint} d="M40 38c0 4-3 6-3 8a3 3 0 0 0 6 0c0-2-3-4-3-8z" />
    </Svg>
  )
}
export function ThumbNameplateArt() {
  return (
    <Svg vb="0 0 80 50">
      <rect {...line} x="8" y="8" width="64" height="34" rx="3" />
      <path {...faint} d="M16 18h30M16 25h48M16 32h22" />
      <circle {...line} cx="64" cy="16" r="2" />
    </Svg>
  )
}
export function ThumbLiveArt() {
  return (
    <Svg vb="0 0 80 50">
      <path {...line} d="M10 16V8h10M60 8h10v8M70 34v8H60M20 42H10v-8" />
      <rect {...faint} x="26" y="16" width="28" height="18" rx="2" />
      <circle cx="68" cy="13" r="2.4" fill="currentColor" />
    </Svg>
  )
}

/* -------------------------------------------------- small cue icons */

export function CueIcon({ name }: { name: 'eye' | 'ask' | 'check' | 'shield' | 'clock' | 'mic' | 'doc' | 'memory' | 'spark' | 'camera' | 'text' }) {
  const paths: Record<string, ReactNode> = {
    eye: <><path {...line} d="M2 12C5.5 6.5 8.5 4.5 12 4.5S18.5 6.5 22 12c-3.5 5.5-6.5 7.5-10 7.5S5.5 17.5 2 12z" /><circle {...line} cx="12" cy="12" r="3.2" /></>,
    ask: <><path {...line} d="M4 5h16v11H10l-5 4v-4H4z" /><path {...line} d="M10 9a2 2 0 1 1 2.8 1.8c-.6.3-.8.7-.8 1.2M12 14v.2" /></>,
    check: <><circle {...line} cx="12" cy="12" r="9" /><path {...line} d="M8 12.5l2.6 2.6L16 9.5" /></>,
    shield: <><path {...line} d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" /><path {...line} d="M12 8v5M12 16v.2" /></>,
    clock: <><circle {...line} cx="12" cy="12" r="9" /><path {...line} d="M12 7v5l3.5 2" /></>,
    mic: <><rect {...line} x="9" y="3" width="6" height="11" rx="3" /><path {...line} d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></>,
    doc: <><path {...line} d="M6 3h8l4 4v14H6z" /><path {...line} d="M9 12h6M9 16h6" /></>,
    memory: <><circle {...line} cx="12" cy="12" r="3" /><path {...line} d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></>,
    spark: <path {...line} d="M12 3v5M12 16v5M3 12h5M16 12h5M6 6l3 3M15 15l3 3M6 18l3-3M15 9l3-3" />,
    camera: <><path {...line} d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle {...line} cx="12" cy="13" r="3.5" /></>,
    text: <path {...line} d="M5 6h14M12 6v13M9 19h6" />,
  }
  return <Svg vb="0 0 24 24" className="ab-cue">{paths[name]}</Svg>
}
