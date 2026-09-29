import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { MoonMark } from '../ui/Icon'
import { useStore } from '../app/store'
import { useSceneEngine } from '../ui/aboutMotion'
import { resetStarTuning, starTuning } from '../ui/Starfield'
import {
  CabinetArt, CameraFrameArt, CircuitArt, CompressorArt, ControlPanelArt, CueIcon, DocPageArt, EyeArt,
  GearArt, MotorArt, PumpArt, ThumbBearingArt, ThumbLiveArt, ThumbNameplateArt, ThumbSealArt, WaveformArt,
} from '../ui/aboutArt'
import { EdgeMore, EdgeScene, SNAPDRAGON_LOGO } from './AboutEdge'
import '../styles/about.css'

/*
 * About — Orion's product story, told as scroll scenes. Section 1b (AboutEdge.tsx), right after
 * the hero ("See. Understand. Act.") and before "The machine is speaking", is the Qualcomm
 * Snapdragon edge architecture — Qwen3-VL-4B-Instruct via GenieX + QAIRT — and the models
 * behind each of Orion's capabilities.
 *
 * Every claim on this page maps to something the app actually does today:
 * photo and live-camera inspection, detector/OCR senses (reported honestly
 * when a model isn't installed), page-cited retrieval from your own manuals,
 * per-job memory that only keeps confirmed facts, answers split into what was
 * observed vs. inferred with safety notices, and a local-first engine with
 * web research that is on by default but always consulted last. Measurements such as temperature and
 * vibration come from the technician — Orion records and reasons over them;
 * it has no sensors of its own, and the copy says so.
 *
 * Motion lives in ../ui/aboutMotion.ts (one engine for all scenes) and
 * ../styles/about.css (transforms/opacity driven by each scene's --p).
 */

type Vars = CSSProperties & Record<`--${string}`, string | number>

/** Deterministic 0..1 noise, so every character gets its own stable path. */
const noise = (i: number, seed: number) => {
  const x = Math.sin(i * 12.9898 + seed * 78.233) * 43758.5453
  return x - Math.floor(x)
}

/**
 * Splits a line into per-character spans so CSS can move each letter on its
 * own schedule. Screen readers get the whole line once (visually hidden
 * copy); the animated letters are hidden from them.
 *   --k  index within the line     --n  line length
 *   --c  index across the headline (from + k), for page-wide staggering
 *   --rx/--ry/--rr  per-letter scatter direction and spin
 */
function Chars({ text, from = 0 }: { text: string; from?: number }) {
  const n = text.length
  return (
    <>
      <span className="ab-vh">{text}</span>
      <span className="ab-chars" aria-hidden="true">
        {Array.from(text).map((ch, k) => {
          const c = from + k
          const rx = ((k + 0.5) / n - 0.5) * 1.5 + (noise(c, 1) - 0.5) * 0.7
          const ry = (noise(c, 2) - 0.62) * 1.3
          const rr = (noise(c, 3) - 0.5) * 160
          return (
            <span key={k} className="ab-ch" style={{ '--k': k, '--n': n, '--c': c, '--rx': rx.toFixed(3), '--ry': ry.toFixed(3), '--rr': rr.toFixed(1) } as Vars}>
              {ch === ' ' ? '\u00a0' : ch}
            </span>
          )
        })}
      </span>
    </>
  )
}

/* ----------------------------------------------------------- content */

const HERO_OBJECTS = [
  { key: 'cam', Art: CameraFrameArt, x: 16, y: 26, mx: 10, my: 16, dx: -1, dy: -0.6, s: 1, d: 'a' },
  { key: 'wave', Art: WaveformArt, x: 80, y: 22, mx: 72, my: 12, dx: 1, dy: -0.7, s: 1.1, d: 'b' },
  { key: 'doc', Art: DocPageArt, x: 86, y: 64, mx: 84, my: 80, dx: 1, dy: 0.5, s: 0.9, d: 'c' },
  { key: 'gear', Art: GearArt, x: 12, y: 70, mx: 14, my: 84, dx: -1, dy: 0.6, s: 0.85, d: 'b' },
  { key: 'eye', Art: EyeArt, x: 30, y: 12, mx: 40, my: 7, dx: -0.4, dy: -1, s: 0.8, d: 'c' },
  { key: 'circuit', Art: CircuitArt, x: 70, y: 86, mx: 50, my: 91, dx: 0.4, dy: 1, s: 0.9, d: 'a' },
]

/** Channels into one conversation. The sub-line says where each comes from. */
const SIGNALS = [
  { key: 'vibration', label: 'Vibration', from: 'you describe where & when', x: 6, y: 20, mx: 2, my: 5, ax: 0.23, ay: 0.52 },
  { key: 'temperature', label: 'Temperature', from: 'your reading, recorded', x: 62, y: 2, mx: 54, my: 5, ax: 0.5, ay: 0.4 },
  { key: 'sound', label: 'Sound', from: 'described by voice', x: 86, y: 38, mx: 2, my: 91, ax: 0.8, ay: 0.52 },
  { key: 'vision', label: 'Vision', from: 'photo & live frames', x: 24, y: 2, mx: 2, my: 79, ax: 0.48, ay: 0.2 },
  { key: 'ocr', label: 'OCR', from: 'nameplates & fault codes', x: 70, y: 86, mx: 54, my: 79, ax: 0.62, ay: 0.64 },
]

const SENSES = [
  { key: 'vision', label: 'Vision', icon: 'eye' as const, line: 'Photos and live frames, read for parts and printed text.', ox: -30, oy: -18, mox: -23, moy: -21, z: 1.05 },
  { key: 'voice', label: 'Voice', icon: 'mic' as const, line: 'Speak the question instead of typing it.', ox: 30, oy: -20, mox: 23, moy: -21, z: 0.9 },
  { key: 'docs', label: 'Documents', icon: 'doc' as const, line: 'Your manuals, indexed page by page.', ox: 34, oy: 14, mox: 25, moy: 4, z: 1 },
  { key: 'memory', label: 'Memory', icon: 'memory' as const, line: 'Each job’s findings and readings, kept.', ox: -2, oy: 28, mox: 0, moy: 23, z: 0.85 },
  { key: 'reason', label: 'Reasoning', icon: 'spark' as const, line: 'Weighs the evidence; names what it can’t confirm.', ox: -34, oy: 12, mox: -25, moy: 4, z: 0.95 },
]

const STAGES = ['See', 'Retrieve', 'Reason', 'Verify', 'Guide']

const FLOW = [
  { title: 'Camera image', line: 'A photo or a live frame from the technician.', icon: 'camera' as const },
  { title: 'Detection', line: 'Detector and OCR read parts and printed text — when those models are installed. If not, Orion says so.', icon: 'eye' as const },
  { title: 'Manual / document', line: 'Local search finds the passage and the page it sits on.', icon: 'doc' as const },
  { title: 'Evidence', line: 'What was seen, what you measured and what the manual says — kept apart.', icon: 'check' as const },
  { title: 'Reasoning', line: 'Observed, inferred and unknown are stated separately, with a confidence.', icon: 'spark' as const },
  { title: 'Technician answer', line: 'Next steps, the cited page, and a safety notice when there is a hazard.', icon: 'ask' as const },
]

const HISTORY = [
  { key: 'm04', name: 'Motor', tag: '#04', when: 'Mar', note: 'Drive-end bearing replaced · 87 °C recorded', Thumb: ThumbBearingArt },
  { key: 'b3', name: 'Pump', tag: 'B3', when: 'May', note: 'Seal weep at the rod end · re-torqued', Thumb: ThumbSealArt },
  { key: 'm07', name: 'Motor', tag: '#07', when: 'Jul', note: 'Nameplate read: 400 VAC · 11.4 A', Thumb: ThumbNameplateArt },
  { key: 'now', name: 'Current', tag: 'inspection', when: 'Now', note: 'Earlier findings for this machine are in context', Thumb: ThumbLiveArt },
]

const FIELD = [
  { key: 'motor', name: 'Motor', Art: MotorArt, words: ['Vibration', 'Heat', 'Bearing', 'Alignment'] },
  { key: 'pump', name: 'Pump', Art: PumpArt, words: ['Leak', 'Seal', 'Pressure', 'Noise'] },
  { key: 'panel', name: 'Control panel', Art: ControlPanelArt, words: ['Fault code', 'Trip', 'Interlock', 'Nameplate'] },
  { key: 'compressor', name: 'Compressor', Art: CompressorArt, words: ['Pressure', 'Heat', 'Relief valve', 'Noise'] },
  { key: 'cabinet', name: 'Electrical cabinet', Art: CabinetArt, words: ['Isolation', 'Trip', 'Contactor', 'Burning smell'] },
]

const WHY = [
  { word: 'See clearly.', cue: 'eye' as const, line: 'Reads parts, labels and nameplates in a photo or a live frame.' },
  { word: 'Ask better.', cue: 'ask' as const, line: 'Asks the one question that narrows the fault next.' },
  { word: 'Verify.', cue: 'check' as const, line: 'Keeps what was seen apart from what is inferred — and cites the page.' },
  { word: 'Act safely.', cue: 'shield' as const, line: 'Puts isolation and hazards in front of the next step.' },
  { word: 'Remember.', cue: 'clock' as const, line: 'Carries confirmed findings to the next visit.' },
]

/* ------------------------------------------------ section 2 connectors */

function MachineRig() {
  const rigRef = useRef<HTMLDivElement | null>(null)
  const machineRef = useRef<HTMLDivElement | null>(null)
  const dotRefs = useRef<(HTMLElement | null)[]>([])
  const [paths, setPaths] = useState<string[]>([])

  // Lines are laid out from the real positions of the labels and the machine
  // (offset geometry, so the scroll transforms never skew them), recomputed
  // only when the rig changes size.
  useLayoutEffect(() => {
    const rig = rigRef.current
    const machine = machineRef.current
    if (!rig || !machine) return
    const compute = () => {
      const mx = machine.offsetLeft, my = machine.offsetTop
      const mw = machine.offsetWidth, mh = machine.offsetHeight
      const next = SIGNALS.map((s, i) => {
        const dot = dotRefs.current[i]
        const label = dot?.offsetParent as HTMLElement | null
        if (!dot || !label) return ''
        const x1 = label.offsetLeft + dot.offsetLeft + dot.offsetWidth / 2
        const y1 = label.offsetTop + dot.offsetTop + dot.offsetHeight / 2
        const x2 = mx + mw * s.ax
        const y2 = my + mh * s.ay
        // An elbow: out horizontally from the label, then straight in.
        const ex = x1 + (x2 - x1) * 0.45
        return `M${x1.toFixed(1)} ${y1.toFixed(1)}H${ex.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`
      })
      setPaths(next)
    }
    compute()
    const ro = new ResizeObserver(compute)
    ro.observe(rig)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="ab-rig" ref={rigRef}>
      <svg className="ab-rig-lines" aria-hidden="true">
        {paths.map((d, i) => d && (
          <g key={SIGNALS[i].key} style={{ '--at': 0.16 + i * 0.07 } as Vars}>
            <path className="ab-wire" d={d} pathLength={1} />
            <path className="ab-wire-pulse" d={d} pathLength={1} />
          </g>
        ))}
      </svg>
      <div className="ab-rig-machine" ref={machineRef}>
        <div className="ab-rig-turn"><MotorArt /></div>
      </div>
      {SIGNALS.map((s, i) => (
        <div
          key={s.key}
          className="ab-signal"
          style={{ '--x': s.x, '--y': s.y, '--mx': s.mx, '--my': s.my, '--at': 0.16 + i * 0.07, '--dx': s.ax < 0.5 ? -1 : 1 } as Vars}
        >
          <i className="ab-signal-dot" ref={(el) => { dotRefs.current[i] = el }} />
          <span className="ab-signal-text">
            <b>{s.label}</b>
            <span>{s.from}</span>
          </span>
        </div>
      ))}
    </div>
  )
}

/* ---------------------------------------------------- local diagram */

function LocalDiagram() {
  const inputs = ['Camera', 'Mic', 'Docs', 'Memory', 'Vision']
  // Desktop: inputs on the left, fan-in to ORION, down to ANSWER.
  const rowsY = [70, 130, 190, 250, 310]
  const wide = (
    <svg className="ab-arch ab-arch-wide" viewBox="0 0 900 420" aria-hidden="true">
      {/* far-off, optional cloud */}
      <g className="ab-arch-cloud">
        <rect x="690" y="24" width="190" height="64" rx="10" />
        <text x="785" y="52">WEB RESEARCH</text>
        <text x="785" y="72" className="dim">consulted last</text>
        <path d="M690 56H560l-60 104" className="ab-arch-optional" />
      </g>
      {inputs.map((name, i) => (
        <g key={name}>
          <text x="96" y={rowsY[i] + 5} className="ab-arch-in">{name.toUpperCase()}</text>
          <path className="ab-arch-line" d={`M126 ${rowsY[i]}H300C360 ${rowsY[i]} 380 190 440 190`} />
          <path className="ab-arch-signal" d={`M126 ${rowsY[i]}H300C360 ${rowsY[i]} 380 190 440 190`} style={{ animationDelay: `${i * -0.7}s` }} />
        </g>
      ))}
      <circle cx="500" cy="190" r="58" className="ab-arch-core" />
      <circle cx="500" cy="190" r="80" className="ab-arch-halo" />
      <text x="500" y="196" className="ab-arch-core-t">ORION</text>
      <path className="ab-arch-line" d="M500 250V360" />
      <path className="ab-arch-signal" d="M500 250V360" />
      <text x="500" y="396" className="ab-arch-out">ANSWER</text>
      <path d="M40 18H640V410H40z" className="ab-arch-device" />
      <text x="54" y="40" className="ab-arch-device-t">YOUR MACHINE</text>
    </svg>
  )
  // Phone: inputs across the top, down into ORION, down to ANSWER.
  const colsX = [34, 102, 170, 238, 306]
  const tall = (
    <svg className="ab-arch ab-arch-tall" viewBox="0 0 340 470" aria-hidden="true">
      {inputs.map((name, i) => (
        <g key={name}>
          <text x={colsX[i]} y="46" className="ab-arch-in sm">{name.toUpperCase()}</text>
          <path className="ab-arch-line" d={`M${colsX[i]} 58V120C${colsX[i]} 170 170 150 170 200`} />
          <path className="ab-arch-signal" d={`M${colsX[i]} 58V120C${colsX[i]} 170 170 150 170 200`} style={{ animationDelay: `${i * -0.7}s` }} />
        </g>
      ))}
      <circle cx="170" cy="252" r="50" className="ab-arch-core" />
      <circle cx="170" cy="252" r="68" className="ab-arch-halo" />
      <text x="170" y="258" className="ab-arch-core-t sm">ORION</text>
      <path className="ab-arch-line" d="M170 304V372" />
      <path className="ab-arch-signal" d="M170 304V372" />
      <text x="170" y="400" className="ab-arch-out sm">ANSWER</text>
      <path d="M8 12H332V420H8z" className="ab-arch-device" />
      <text x="20" y="410" className="ab-arch-device-t sm">YOUR MACHINE</text>
      <g className="ab-arch-cloud">
        <rect x="90" y="434" width="160" height="30" rx="8" />
        <text x="170" y="454" className="sm">WEB · CONSULTED LAST</text>
      </g>
    </svg>
  )
  return <div className="ab-arch-wrap">{wide}{tall}</div>
}

/* --------------------------------------------------------------- page */

export function About() {
  const { go, newConversation } = useStore()
  const rootRef = useRef<HTMLDivElement | null>(null)

  // The ending drives the starfield: it thins out, the stars rush inward,
  // then everything settles almost still.
  const listeners = useMemo(() => ({
    ending: (p: number) => {
      const reduce = document.documentElement.classList.contains('reduce-motion')
      starTuning.density = 1 - 0.7 * p
      if (reduce) { starTuning.speed = 1; return }
      starTuning.speed = p < 0.72 ? 1 + 2.6 * (p / 0.72) : 3.6 - 3.3 * Math.min(1, (p - 0.72) / 0.28)
    },
  }), [])
  // Field objects draw themselves in: every stroke gets pathLength="1" so CSS
  // can run stroke-dashoffset 1 (hidden) → 0 (drawn). Dashes only measure
  // correctly in the art's own units, so the drawings drop non-scaling-stroke
  // (see about.css) and instead get a stroke width (--sw) worked out here to
  // keep the same 1.4px on screen at any size.
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    const svgs = Array.from(root.querySelectorAll<SVGSVGElement>('.ab-obj-art svg'))
    svgs.forEach((svg) =>
      svg.querySelectorAll('path, rect, circle, ellipse, line, polyline, polygon')
        .forEach((el) => el.setAttribute('pathLength', '1')))
    const fit = () => svgs.forEach((svg) => {
      const w = (svg.parentElement as HTMLElement | null)?.offsetWidth ?? 0
      const vb = svg.viewBox.baseVal?.width || w
      if (w) svg.style.setProperty('--sw', (1.4 * vb / w).toFixed(4))
    })
    fit()
    const ro = new ResizeObserver(fit)
    svgs.forEach((svg) => svg.parentElement && ro.observe(svg.parentElement))
    return () => ro.disconnect()
  }, [])
  useSceneEngine(rootRef, listeners)
  useEffect(() => () => resetStarTuning(), [])

  const start = () => {
    newConversation()
    go('chat')
  }

  return (
    <div className="ab-shell">
      <div className="ab-grain" aria-hidden="true" />
      <div className="ab" ref={rootRef}>

        {/* 1 — HERO */}
        <section className="ab-scene ab-hero" data-scene="pin" style={{ '--len': 3.8 } as Vars} aria-labelledby="ab-hero-t">
          <div className="ab-stage">
            <div className="ab-warp" aria-hidden="true">
              {[0, 1, 2, 3].map((k) => <i key={k} style={{ '--k': k } as Vars} />)}
            </div>
            <div className="ab-hero-objects" aria-hidden="true">
              {HERO_OBJECTS.map(({ key, Art, ...o }, i) => (
                <div
                  key={key}
                  className={`ab-float ab-drift-${o.d}`}
                  style={{ '--x': o.x, '--y': o.y, '--mx': o.mx, '--my': o.my, '--dx': o.dx, '--dy': o.dy, '--s': o.s, '--i': i } as Vars}
                >
                  <Art />
                </div>
              ))}
            </div>
            <div className="ab-hero-copy">
              <span className="ab-hero-mark ab-seq" style={{ '--i': 0 } as Vars}><MoonMark size={40} /></span>
              <p className="ab-hero-name ab-seq" style={{ '--i': 1 } as Vars}>Orion</p>
              <h1 id="ab-hero-t" className="ab-display ab-hero-title">
                <span className="ab-seq ab-light" style={{ '--i': 2 } as Vars}><Chars text="See." from={0} /></span>
                <span className="ab-seq" style={{ '--i': 3 } as Vars}><Chars text="Understand." from={4} /></span>
                <span className="ab-seq ab-light" style={{ '--i': 4 } as Vars}><Chars text="Act." from={15} /></span>
              </h1>
              <p className="ab-hero-sub ab-seq" style={{ '--i': 5 } as Vars}>
                A multimodal field-technician assistant built to help you understand machines in context.
              </p>
            </div>
            <span className="ab-scroll-hint ab-seq" style={{ '--i': 7 } as Vars} aria-hidden="true"><i /></span>
          </div>
        </section>

        {/* 1b — BUILT FOR SNAPDRAGON: the edge architecture and the models Orion uses */}
        <EdgeScene />
        <EdgeMore />

        {/* 2 — THE MACHINE IS SPEAKING */}
        <section className="ab-scene ab-machine" data-scene="pin" style={{ '--len': 3.8 } as Vars} aria-labelledby="ab-machine-t">
          <div className="ab-stage">
            <div className="ab-machine-copy">
              <h2 id="ab-machine-t" className="ab-display ab-machine-title">
                <span>The machine</span>
                <span>is speaking.</span>
              </h2>
              <p className="ab-kicker ab-machine-sub">Orion helps you listen.</p>
              <p className="ab-note ab-machine-note">
                Orion has no sensors of its own. It reads what the camera sees, and records what you
                measure and describe — then reasons across all of it at once.
              </p>
            </div>
            <MachineRig />
          </div>
        </section>

        {/* 3 — ONE CONVERSATION. MANY SENSES. */}
        <section className="ab-scene ab-senses" data-scene="pin" style={{ '--len': 4 } as Vars} aria-labelledby="ab-senses-t">
          <div className="ab-stage">
            <h2 id="ab-senses-t" className="ab-display ab-senses-title">
              <span>One conversation.</span>
              <span className="ab-light">Many senses.</span>
            </h2>
            <div className="ab-orbit" aria-hidden="true">
              <i className="ab-ring r1" /><i className="ab-ring r2" /><i className="ab-ring r3" />
            </div>
            <div className="ab-senses-core" aria-hidden="true"><MoonMark size={72} /></div>
            <ul className="ab-senses-list">
              {SENSES.map((s, i) => (
                <li
                  key={s.key}
                  className="ab-sense"
                  style={{ '--ox': s.ox, '--oy': s.oy, '--mox': s.mox, '--moy': s.moy, '--z': s.z, '--st': 0.2 + i * 0.1, '--i': i } as Vars}
                >
                  <span className="ab-sense-icon"><CueIcon name={s.icon} /></span>
                  <b>{s.label}</b>
                  <span>{s.line}</span>
                </li>
              ))}
            </ul>
            <p className="ab-note ab-senses-note">All five meet in one thread — a photo, a spoken question and a page of the manual answered together.</p>
          </div>
        </section>

        {/* 4 — THE PIPELINE */}
        <section className="ab-scene ab-pipe" data-scene="pin" style={{ '--len': 4.6 } as Vars} aria-labelledby="ab-pipe-t">
          <div className="ab-stage">
            <h2 id="ab-pipe-t" className="ab-vh">The pipeline: see, retrieve, reason, verify, guide</h2>
            <div className="ab-pipe-words" aria-hidden="true">
              <div className="ab-pipe-row">
                {STAGES.map((w, i) => (
                  <span key={w} className="ab-pipe-word" style={{ '--at': i / 5, '--next': i === STAGES.length - 1 ? 2 : (i + 1) / 5 } as Vars}>
                    <span className="ab-display">{w}</span>
                    {i < STAGES.length - 1 && <em>→</em>}
                  </span>
                ))}
              </div>
            </div>
            <ol className="ab-flow">
              <li className="ab-flow-rail" aria-hidden="true"><i className="ab-flow-fill" /><i className="ab-flow-track"><i className="ab-flow-dot" /></i></li>
              {FLOW.map((f, i) => (
                <li key={f.title} className="ab-flow-node" style={{ '--at': i / 5 - 0.03, '--next': (i + 1) / 5 - 0.03 } as Vars}>
                  <span className="ab-flow-icon"><CueIcon name={f.icon} /></span>
                  <b>{f.title}</b>
                  <span>{f.line}</span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* 5 — MEMORY */}
        <section className="ab-scene ab-memory" data-scene="pin" style={{ '--len': 4 } as Vars} aria-labelledby="ab-memory-t">
          <div className="ab-stage">
            <h2 id="ab-memory-t" className="ab-display ab-memory-title">
              <span>Every inspection</span>
              <span className="ab-light">becomes context.</span>
            </h2>
            <div className="ab-timeline">
              <div className="ab-tl-rail">
                <span className="ab-tl-year">2026</span>
                <i className="ab-tl-line" />
                {HISTORY.map((h, i) => (
                  <div key={h.key} className={`ab-tl-node${i === HISTORY.length - 1 ? ' is-now' : ''}`} style={{ '--at': i / 3 - 0.06, '--next': (i + 1) / 3 - 0.06, '--i': i } as Vars}>
                    <figure className="ab-tl-card">
                      <span className="ab-tl-thumb"><h.Thumb /></span>
                      <figcaption>{h.note}</figcaption>
                    </figure>
                    <i className="ab-tl-dot" />
                    <span className="ab-tl-label"><b>{h.name}</b> {h.tag}</span>
                    <span className="ab-tl-when">{h.when}</span>
                  </div>
                ))}
              </div>
            </div>
            <p className="ab-note ab-memory-note">
              On a return visit Orion brings the machine’s earlier findings, readings and confirmed repairs
              into the answer. It keeps only what was confirmed — a guess is never saved as a fact.
              <span className="ab-caption">Illustrative job history.</span>
            </p>
          </div>
        </section>

        {/* 6 — BUILT FOR THE FIELD */}
        <section className="ab-scene ab-field" data-scene="pin" style={{ '--len': 7 } as Vars} aria-labelledby="ab-field-t">
          <div className="ab-stage">
            <h2 id="ab-field-t" className="ab-display ab-field-title">
              <span>Built</span>
              <span className="ab-light">for the field.</span>
            </h2>
            <div className="ab-field-stage">
              {FIELD.map(({ key, name, Art, words }, i) => (
                <figure key={key} className="ab-obj" style={{ '--i': i } as Vars}>
                  <span className="ab-display ab-obj-num" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
                  <div className="ab-obj-art"><Art /><i className="ab-obj-scan" aria-hidden="true" /></div>
                  <figcaption className="ab-obj-name"><span>{String(i + 1).padStart(2, '0')} / 05</span>{name}</figcaption>
                  <ul className="ab-obj-words" aria-label={`${name}: topics Orion can work through`}>
                    {words.map((w, j) => <li key={w} style={{ '--j': j } as Vars}>{w}</li>)}
                  </ul>
                </figure>
              ))}
            </div>
            <div className="ab-field-progress" aria-hidden="true">
              {FIELD.map((f, i) => <i key={f.key} style={{ '--i': i } as Vars} />)}
            </div>
            <p className="ab-note ab-field-note">
              The faults Orion works through with you — from what you see, measure and describe. Where it can’t
              confirm something, it says so and asks for the reading.
            </p>
          </div>
        </section>

        {/* 7 — LOCAL BY DESIGN */}
        <section className="ab-scene ab-local" data-scene="flow" aria-labelledby="ab-local-t">
          <h2 id="ab-local-t" className="ab-display ab-local-title" data-reveal>
            <span>Your data.</span>
            <span className="ab-light">Your device.</span>
          </h2>
          <div data-reveal style={{ '--i': 1 } as Vars}><LocalDiagram /></div>
          <p className="ab-note ab-local-note" data-reveal style={{ '--i': 2 } as Vars}>
            Orion’s engine is built to run on your own machine: documents, camera frames, audio and job memory
            stay with it. Web research is on by default, but it is always the last place Orion looks — only when
            your manuals and job memory come up short — and one switch in Settings turns it off. Profile → System
            status shows what is actually running right now.
          </p>
        </section>

        {/* 8 — WHY ORION */}
        <section className="ab-scene ab-why" data-scene="flow" aria-label="Why Orion">
          <ul className="ab-why-list">
            {WHY.map((w, i) => (
              <li key={w.word} className="ab-why-item" data-reveal style={{ '--i': 0 } as Vars}>
                <span className="ab-why-cue" aria-hidden="true"><CueIcon name={w.cue} /></span>
                <span className="ab-display ab-why-word">{w.word}</span>
                <span className="ab-why-line">{w.line}</span>
                <span className="ab-why-n" aria-hidden="true">0{i + 1}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* 9 — ENDING */}
        <section className="ab-scene ab-end" data-scene="pin" data-scene-id="ending" style={{ '--len': 3.8 } as Vars} aria-labelledby="ab-end-t">
          <div className="ab-stage">
            <div className="ab-end-dark" aria-hidden="true" />
            <div className="ab-end-copy">
              <span className="ab-end-markwrap" aria-hidden="true">
                {[0, 1, 2].map((k) => <i key={k} className="ab-end-ring" style={{ '--k': k } as Vars} />)}
                <span className="ab-end-mark"><MoonMark size={56} /></span>
              </span>
              <h2 id="ab-end-t" className="ab-display ab-end-title">
                <span><Chars text="See clearer." /></span>
                <span className="ab-light"><Chars text="Work smarter." /></span>
              </h2>
              <p className="ab-end-name"><Chars text="Orion" /></p>
              <button type="button" className="ab-cta" onClick={start}>
                <i className="ab-cta-edge t" aria-hidden="true" />
                <i className="ab-cta-edge b" aria-hidden="true" />
                <i className="ab-cta-edge l" aria-hidden="true" />
                <i className="ab-cta-edge r" aria-hidden="true" />
                <span className="ab-cta-label">Start a conversation</span>
              </button>
              <p className="ab-end-credit">
                {SNAPDRAGON_LOGO && <img src={SNAPDRAGON_LOGO} alt="" aria-hidden="true" />}
                <span>Designed for Qualcomm Snapdragon</span>
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
