import { Brandmark, Icon } from '../ui/Icon'
import { Cap } from '../ui/bits'

/**
 * Intentionally blank. The layout, spacing and type scale are set so real
 * content can drop straight in — nothing about the product or the team is
 * invented here.
 */
export function About() {
  return (
    <div className="about">
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18 }}>
        <Brandmark size={58} />
        <h1>About <b>VisionField Copilot</b></h1>
      </div>

      <div className="slot">
        <Icon name="text" size={22} stroke="rgba(255,255,255,.28)" width={1.6} />
        <Cap>Content to be added</Cap>
        <p>
          This page is intentionally empty. The layout, spacing and type scale are set so text, team
          details or credits can drop straight in.
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', justifyContent: 'center' }}>
        <span className="status"><Icon name="cpu" size={13} stroke="var(--vf-muted)" width={1.9} />Version 1.0.0 · build 2026.09.19</span>
        <span style={{ width: 1, height: 16, background: 'rgba(255,255,255,.18)' }} />
        <span className="status"><Icon name="lock" size={13} stroke="var(--vf-ok)" width={1.9} />Runs entirely on this device</span>
      </div>
    </div>
  )
}
