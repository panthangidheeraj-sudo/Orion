import { Icon } from './Icon'
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

function items(stroke: (on: boolean) => string, iconSize: number, route: Route, go: (r: Route) => void) {
  return NAV.map((n) => {
    const on = isCurrent(n.route, route)
    return (
      <a
        key={n.route}
        href={`#${n.route}`}
        className="navitem"
        aria-current={on ? 'page' : undefined}
        onClick={(e) => { e.preventDefault(); go(n.route) }}
      >
        <Icon name={n.icon} size={iconSize} stroke={stroke(on)} />
        <span>{n.label}</span>
      </a>
    )
  })
}

export function TopBar() {
  const { route, go } = useStore()
  return (
    <nav className="vf-nav" aria-label="Primary">
      {items((on) => (on ? 'var(--vf-on-invert)' : 'var(--vf-muted)'), 16, route, go)}
    </nav>
  )
}

export function TabBar() {
  const { route, go } = useStore()
  return (
    <nav className="tabbar" aria-label="Primary">
      {items((on) => (on ? 'var(--vf-text)' : 'var(--vf-muted)'), 20, route, go)}
    </nav>
  )
}
