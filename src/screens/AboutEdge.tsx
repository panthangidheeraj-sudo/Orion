import type { CSSProperties } from 'react'
import { useStore } from '../app/store'
import type { BackendInfo } from '../app/api'
import { CueIcon } from '../ui/aboutArt'

/*
 * About → "Built for Snapdragon": Orion's edge-computing architecture.
 *
 * Two sections:
 *   EdgeScene  a pinned scene — the stack diagram builds layer by layer
 *              (Snapdragon → Hexagon NPU → QAIRT → GenieX →
 *              Qwen3-VL-4B-Instruct → Orion → See · Understand · Verify ·
 *              Guide) over a generic chip-package drawing.
 *   EdgeMore   a flowing section — target Snapdragon platforms, five cards
 *              explaining the Qualcomm stack itself (Qwen3-VL-4B-Instruct,
 *              GenieX, QAIRT, Qualcomm AI Hub, Device Cloud), the two
 *              required factuality statements, and a separate five-card
 *              group for the broader Orion capability stack (only
 *              Reasoning runs the Qualcomm path above).
 *
 * FACTUALITY. Every layer carries one of three honest states:
 *   Designed for  the architecture targets it
 *   Implemented   the code for it exists in Orion today
 *   Validated     ONLY when this device's backend reports the reasoning role
 *                 running as GenieX/QAIRT with npu: true — a verdict the
 *                 backend gives only after the model loads on the QAIRT plugin
 *                 and a probe generation runs on the NPU (app/models/geniex.py).
 * Nothing here is hard-coded as validated, and no performance figures appear.
 *
 * LOGO. The official Snapdragon logo is Qualcomm's trademark, so it is not
 * redrawn here. Drop the official file from Qualcomm's brand / hackathon kit at
 *   src/assets/brand/snapdragon-logo.svg   (or .png / .webp)
 * and it appears in this section automatically. Use it as Qualcomm's brand
 * guidelines allow (clear space, no recolouring or distortion).
 */

type Vars = CSSProperties & Record<`--${string}`, string | number>

const logoFiles = import.meta.glob('../assets/brand/snapdragon-logo.{svg,png,webp}', {
  eager: true, query: '?url', import: 'default',
}) as Record<string, string>
export const SNAPDRAGON_LOGO: string | undefined = Object.values(logoFiles)[0]

type Tier = 'designed' | 'implemented' | 'validated'
const TIER_LABEL: Record<Tier, string> = {
  designed: 'Designed for',
  implemented: 'Implemented',
  validated: 'Validated · this device',
}

const STACK: { key: string; name: string; sub: string; tier: Tier; hw?: boolean }[] = [
  { key: 'soc', name: 'Qualcomm Snapdragon', sub: 'System-on-chip — Oryon CPU, Adreno GPU, Hexagon NPU', tier: 'designed', hw: true },
  { key: 'npu', name: 'Hexagon NPU', sub: 'Dedicated neural accelerator — the compiled model executes here', tier: 'designed', hw: true },
  { key: 'qairt', name: 'QAIRT', sub: 'Qualcomm AI Runtime — compiles and places the model on the NPU', tier: 'designed', hw: true },
  { key: 'geniex', name: 'GenieX', sub: 'On-device generative AI runtime — loads and executes the reasoning model', tier: 'implemented', hw: true },
  { key: 'qwen', name: 'Qwen3-VL-4B-Instruct', sub: 'Vision-language reasoning model — text and image understanding', tier: 'designed', hw: true },
  { key: 'orion', name: 'Orion', sub: 'Router · tools · retrieval · memory · safety checks', tier: 'implemented' },
]
const OUTPUT = ['See', 'Understand', 'Verify', 'Guide']
const ROWS = STACK.length + 1

const SPECS = [
  { k: 'Reasoning', v: 'Qwen3-VL-4B-Instruct' },
  { k: 'Runtime', v: 'GenieX · QAIRT' },
  { k: 'Precision', v: 'W4A16' },
  { k: 'Host', v: 'Windows on Snapdragon · ARM64' },
]

const PLATFORMS = [
  { name: 'Snapdragon X Elite', d: 0.9 },
  { name: 'Snapdragon X Plus 8-Core', d: 1.5 },
  { name: 'Snapdragon X2 Elite', d: 1.1 },
]

/** The Qualcomm/Snapdragon stack, explained one piece at a time. */
const STACK_CARDS = [
  { t: 'Qwen3-VL-4B-Instruct', l: 'Orion’s multimodal reasoning model — understands text + images and handles conversation, semantic routing and technical reasoning.', icon: 'spark' as const },
  { t: 'GenieX', l: 'Qualcomm’s on-device generative AI runtime used to load and execute the reasoning model.', icon: 'memory' as const },
  { t: 'QAIRT', l: 'Qualcomm AI Engine Direct runtime used for the compiled NPU execution path.', icon: 'check' as const },
  { t: 'Qualcomm AI Hub', l: 'Model optimization, compilation, profiling and deployable assets for Qualcomm devices.', icon: 'doc' as const },
  { t: 'Device Cloud', l: 'Qualcomm-hosted Snapdragon hardware used to validate the model/runtime remotely when physical Snapdragon hardware is unavailable.', icon: 'clock' as const },
]

/** The broader Orion capability stack — only Reasoning runs the Qualcomm path above. */
const CAPS = [
  { t: 'Vision', l: 'Object detection • classification • segmentation • tracking • OCR', icon: 'eye' as const },
  { t: 'Reasoning', l: 'Qwen3-VL-4B-Instruct • text + image reasoning', icon: 'spark' as const },
  { t: 'Knowledge', l: 'Documents • retrieval • job memory', icon: 'doc' as const },
  { t: 'Voice', l: 'Speech-to-text • text-to-speech', icon: 'mic' as const },
  { t: 'Safety', l: 'Evidence separation • hazard checks • verification', icon: 'shield' as const },
]

/** True only on the runtime's own evidence — see the note at the top. */
export function npuValidated(b: BackendInfo): boolean {
  const m = b.model
  return Boolean(b.online && m && m.npu && !m.synthetic && m.provider === 'GenieX/QAIRT'
    && (b.ready ?? []).includes('reasoning'))
}

/* ------------------------------------------------------------ chip art */

/** A generic chip package seen from above — package, die, pins, traces.
 *  Not a drawing of any real product. Traces carry pathLength=1 so CSS can
 *  draw them in with scroll. */
function ChipArt() {
  const pins = Array.from({ length: 10 }, (_, i) => 104 + i * 21.3)
  const traces: string[] = []
  pins.forEach((x, i) => {
    const bend = 30 + ((i * 37) % 44)
    traces.push(`M${x} 80V${80 - bend}H${x + (i % 2 ? 26 : -26)}V0`)
    traces.push(`M${x} 320V${320 + bend}H${x + (i % 2 ? -26 : 26)}V400`)
    traces.push(`M80 ${x}H${80 - bend}V${x + (i % 2 ? 26 : -26)}H0`)
    traces.push(`M320 ${x}H${320 + bend}V${x + (i % 2 ? -26 : 26)}H400`)
  })
  return (
    <svg viewBox="0 0 400 400" aria-hidden="true" focusable="false">
      <g className="ab-chip-grid">
        {Array.from({ length: 9 }, (_, i) => <path key={i} d={`M${40 + i * 40} 0V400M0 ${40 + i * 40}H400`} />)}
      </g>
      <g className="ab-chip-traces">
        {traces.map((d, i) => <path key={i} d={d} pathLength={1} style={{ '--t': (i % 8) / 8 } as Vars} />)}
      </g>
      <g className="ab-chip-pins">
        {pins.map((x) => (
          <g key={x}>
            <rect x={x - 4} y="68" width="8" height="12" rx="1.5" />
            <rect x={x - 4} y="320" width="8" height="12" rx="1.5" />
            <rect x="68" y={x - 4} width="12" height="8" rx="1.5" />
            <rect x="320" y={x - 4} width="12" height="8" rx="1.5" />
          </g>
        ))}
      </g>
      <rect className="ab-chip-pkg" x="80" y="80" width="240" height="240" rx="18" />
      <rect className="ab-chip-die-glow" x="130" y="130" width="140" height="140" rx="10" />
      <rect className="ab-chip-die" x="140" y="140" width="120" height="120" rx="8" />
      <g className="ab-chip-cells">
        {Array.from({ length: 16 }, (_, i) => (
          <rect key={i} x={150 + (i % 4) * 26} y={150 + Math.floor(i / 4) * 26} width="20" height="20" rx="2" style={{ '--t': i / 16 } as Vars} />
        ))}
      </g>
      <circle className="ab-chip-dot" cx="98" cy="98" r="4" />
    </svg>
  )
}

function Logo({ className }: { className: string }) {
  if (!SNAPDRAGON_LOGO) return null
  return <img className={className} src={SNAPDRAGON_LOGO} alt="Snapdragon" draggable={false} />
}

/* -------------------------------------------------------------- scenes */

export function EdgeScene() {
  const { backend } = useStore()
  const validated = npuValidated(backend)

  return (
    <section className="ab-scene ab-edge" data-scene="pin" style={{ '--len': 4.4 } as Vars} aria-labelledby="ab-edge-t">
      <div className="ab-stage">
        <div className="ab-chip" aria-hidden="true"><div className="ab-chip-tilt"><ChipArt /></div></div>

        <div className="ab-edge-copy">
          <Logo className="ab-edge-badge" />
          <p className="ab-kicker ab-edge-kicker">
            <span>Edge architecture</span>
          </p>
          <h2 id="ab-edge-t" className="ab-display ab-edge-title">
            <span>Built for</span>
            <span className="ab-light">Snapdragon.</span>
          </h2>
          <p className="ab-note ab-edge-lead">
            Local-first multimodal intelligence, designed around Qualcomm Snapdragon edge platforms.
          </p>
          <dl className="ab-specs">
            {SPECS.map((s, i) => (
              <div key={s.k} className="ab-spec" style={{ '--i': i } as Vars}>
                <dt>{s.k}</dt><dd>{s.v}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="ab-stack-wrap">
          <ol className="ab-stack" aria-label="Orion's target edge stack, from hardware up">
            <li className="ab-stack-rail" aria-hidden="true"><i className="ab-stack-fill" /><i className="ab-stack-track"><i className="ab-stack-dot" /></i></li>
            {STACK.map((l, i) => {
              const tier: Tier = validated && l.hw ? 'validated' : l.tier
              return (
                <li key={l.key} className={`ab-layer is-${tier}`} style={{ '--at': i / ROWS, '--next': (i + 1) / ROWS } as Vars}>
                  <span className="ab-layer-pin" aria-hidden="true" />
                  <span className="ab-layer-body">
                    <b className="ab-layer-name">
                      {l.key === 'soc' && <Logo className="ab-layer-logo" />}
                      {l.name}
                    </b>
                    <span className="ab-layer-sub">{l.sub}</span>
                  </span>
                  <span className="ab-layer-tag">{TIER_LABEL[tier]}</span>
                </li>
              )
            })}
            <li className="ab-layer ab-layer-out is-implemented" style={{ '--at': STACK.length / ROWS, '--next': 2 } as Vars}>
              <span className="ab-layer-pin" aria-hidden="true" />
              <span className="ab-layer-body">
                <b className="ab-layer-name ab-out-words">
                  {OUTPUT.map((w, i) => (
                    <span key={w} style={{ '--j': i } as Vars}>{w}{i < OUTPUT.length - 1 && <em aria-hidden="true"> • </em>}</span>
                  ))}
                </b>
              </span>
            </li>
          </ol>
          <p className={`ab-edge-status${validated ? ' is-validated' : ''}`}>
            <i aria-hidden="true" />
            {validated
              ? <>Validated on this device — the runtime reports {backend.model?.model_id} on the Snapdragon NPU through GenieX/QAIRT.</>
              : <>Hardware validation pending. Layers are marked as designed-for or implemented until Orion’s own runtime confirms the model on a Snapdragon NPU.</>}
          </p>
        </div>
      </div>
    </section>
  )
}

export function EdgeMore() {
  return (
    <section className="ab-scene ab-edge-more" data-scene="flow" aria-label="Target platforms and capabilities">
      <div className="ab-plat-head" data-reveal>
        <p className="ab-kicker">Target platforms</p>
        <p className="ab-note">
          The Qualcomm Snapdragon platforms targeted by the GenieX + QAIRT Qwen3-VL-4B-Instruct reasoning path.
        </p>
      </div>
      <ul className="ab-plats">
        {PLATFORMS.map((p, i) => (
          <li key={p.name} className="ab-plat" data-reveal style={{ '--i': i, '--d': p.d } as Vars}>
            <div className="ab-plat-float">
              <span className="ab-plat-chip" aria-hidden="true"><i /></span>
              {/* "8-Core" must not break at its hyphen. */}
              <b>{p.name.split(' ').map((w, j) => <span key={j} className="ab-nobr">{w}{' '}</span>)}</b>
              <span className="ab-plat-sub">Windows on Snapdragon · ARM64</span>
              <span className="ab-plat-tag">Target platform</span>
            </div>
          </li>
        ))}
      </ul>

      <div className="ab-edge-notes" data-reveal>
        <p className="ab-edge-stackline">
          Orion’s Qualcomm reasoning path is <span>Qwen3-VL-4B-Instruct through GenieX + QAIRT.</span>
        </p>
      </div>

      <div className="ab-plat-head" data-reveal>
        <p className="ab-kicker">The Qualcomm stack</p>
        <p className="ab-note">
          Qualcomm-supported deployment path — from the reasoning model to the hardware it targets.
        </p>
      </div>
      <ul className="ab-caps">
        {STACK_CARDS.map((c, i) => (
          <li key={c.t} className="ab-cap" data-reveal style={{ '--i': i % 3 } as Vars}>
            <span className="ab-cap-icon" aria-hidden="true"><CueIcon name={c.icon} /></span>
            <b>{c.t}</b>
            <span>{c.l}</span>
          </li>
        ))}
      </ul>

      <div className="ab-edge-notes" data-reveal>
        <p className="ab-note">
          Other Orion capabilities use separate model adapters and runtimes; they should not be visually
          presented as Qualcomm models unless they have actually been validated through Qualcomm AI Hub.
        </p>
      </div>

      <div className="ab-plat-head" data-reveal>
        <p className="ab-kicker">The broader Orion capability stack</p>
        <p className="ab-note">
          Reasoning is the Qualcomm-supported path above. The rest of Orion runs on its own adapters and
          runtimes, target edge reasoning stack aside.
        </p>
      </div>
      <ul className="ab-caps">
        {CAPS.map((c, i) => (
          <li key={c.t} className="ab-cap" data-reveal style={{ '--i': i % 3 } as Vars}>
            <span className="ab-cap-icon" aria-hidden="true"><CueIcon name={c.icon} /></span>
            <b>{c.t}</b>
            <span>{c.l}</span>
          </li>
        ))}
      </ul>

      <div className="ab-edge-notes" data-reveal>
        <p className="ab-note">
          Cloud services can complement Orion, but the architecture is designed around local-first operation
          wherever capable Qualcomm hardware and models are available.
        </p>
      </div>
    </section>
  )
}
