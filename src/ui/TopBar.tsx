import { useState } from 'react'
import { Icon, MoonMark } from './Icon'
import GooeyNav, { type GooeyNavItem } from './GooeyNav'
import { useStore } from '../app/store'
import type { Route } from '../app/types'

const NAV: { label: string; route: Route; icon: string }[] = [
  { label: 'Home', route: 'home', icon: 'home' },
  { label: 'Convo', route: 'convo', icon: 'chat' },
  { label: 'About', route: 'about', icon: 'info' },
  { label: 'Profile', route: 'settings', icon: 'user' },
]

/** Convo owns the whole conversation branch, so it stays lit inside a thread. */
function isCurrent(route: Route, active: Route) {
  if (route === 'convo') {
    return ['convo', 'chat', 'live', 'files', 'doc', 'reports'].includes(active)
  }
  return route === active
}

function useNav(iconSize: number) {
  const { route, go } = useStore()
  const items: GooeyNavItem[] = NAV.map((n) => ({
    label: n.label,
    href: `#${n.route}`,
    // currentColor, so the icon flips with the label when its item is active.
    icon: <Icon name={n.icon} size={iconSize} stroke="currentColor" />,
  }))
  const activeIndex = NAV.findIndex((n) => isCurrent(n.route, route))
  const onSelect = (i: number) => go(NAV[i].route)
  return { items, activeIndex, onSelect }
}

/** Desktop / tablet: the centred pill under the logo. */
export function TopBar() {
  const nav = useNav(16)
  return (
    <div className="vf-nav">
      {/* A quieter version of the phone tab bar's burst: fewer, smaller bubbles,
          stretched to hug this wider pill (see GooeyNav makeParticles). */}
      <GooeyNav {...nav} variant="top" ariaLabel="Primary" particleDistances={[60, 8]} particleCount={6} />
    </div>
  )
}

/** Orion's mark, pinned to the top-left corner of the app shell. Sits beside
 * the centred nav pill rather than inside it, so the nav stays centred.
 * Clicking it refreshes the app: the mark turns once, then the page reloads
 * (straight away under Reduce Motion). */
export function Logo() {
  const { prefs } = useStore()
  const [spinning, setSpinning] = useState(false)
  const refresh = () => {
    if (spinning) return
    if (prefs.reduceMotion) { window.location.reload(); return }
    setSpinning(true)
    window.setTimeout(() => window.location.reload(), 420)
  }
  return (
    <button
      type="button"
      className={spinning ? 'vf-logo is-refreshing' : 'vf-logo'}
      aria-label="Refresh Orion"
      title="Refresh"
      onClick={refresh}
    >
      <MoonMark size={44} />
    </button>
  )
}

/** Phone: fixed to the bottom edge, above the safe area. */
export function TabBar() {
  const nav = useNav(20)
  return (
    <div className="tabbar">
      <GooeyNav {...nav} variant="bottom" ariaLabel="Primary" particleDistances={[60, 8]} particleCount={12} />
    </div>
  )
}
