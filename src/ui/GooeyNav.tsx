// Ported from React Bits <GooeyNav /> (JS + CSS variant, no dependencies).
// https://reactbits.dev/components/gooey-nav
//
// Changes from the upstream source, for Orion's shell:
//  - TypeScript, and the active item is CONTROLLED (`activeIndex` + `onSelect`)
//    so it follows the app's route — navigating from a button elsewhere moves
//    the pill too, not just clicking the nav.
//  - Items can carry an icon. Upstream's second "text" overlay layer copied
//    `innerText` over the pill; with icons that would double-draw a misaligned
//    label, so the li's own active state (white pill, dark text) is used.
//  - The burst only fires when the active item actually changes — never on
//    mount or re-render — and is skipped under Orion's Reduce Motion.
//  - `variant="bottom"` stacks icon over label for the phone tab bar.
//  - Styles are scoped in GooeyNav.css (no global `.particle` / `.point`).

import { useCallback, useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import './GooeyNav.css'

export interface GooeyNavItem {
  label: string
  href: string
  icon?: ReactNode
}

export interface GooeyNavProps {
  items: GooeyNavItem[]
  /** -1 when no item is current (e.g. a screen outside the nav). */
  activeIndex: number
  onSelect: (index: number) => void
  variant?: 'top' | 'bottom'
  ariaLabel?: string
  className?: string
  animationTime?: number
  particleCount?: number
  particleDistances?: [number, number]
  particleR?: number
  timeVariance?: number
  colors?: number[]
}

const reducedMotion = () =>
  typeof document !== 'undefined' && document.documentElement.classList.contains('reduce-motion')

export default function GooeyNav({
  items,
  activeIndex,
  onSelect,
  variant = 'top',
  ariaLabel = 'Primary',
  className = '',
  animationTime = 600,
  particleCount = 15,
  particleDistances = [90, 10],
  particleR = 100,
  timeVariance = 300,
  colors = [1, 2, 3, 1, 2, 3, 1, 4],
}: GooeyNavProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const navRef = useRef<HTMLUListElement | null>(null)
  const filterRef = useRef<HTMLSpanElement | null>(null)
  const prevIndex = useRef(activeIndex)
  const timers = useRef<number[]>([])

  const noise = (n = 1) => n / 2 - Math.random() * n

  const getXY = (distance: number, pointIndex: number, totalPoints: number): [number, number] => {
    const angle = ((360 + noise(8)) / totalPoints) * pointIndex * (Math.PI / 180)
    return [distance * Math.cos(angle), distance * Math.sin(angle)]
  }

  const createParticle = (i: number, t: number, d: [number, number], r: number) => {
    const rotate = noise(r / 10)
    return {
      start: getXY(d[0], particleCount - i, particleCount),
      end: getXY(d[1] + noise(7), particleCount - i, particleCount),
      time: t,
      scale: 1 + noise(0.2),
      color: colors[Math.floor(Math.random() * colors.length)],
      rotate: rotate > 0 ? (rotate + r / 20) * 10 : (rotate - r / 20) * 10,
    }
  }

  const makeParticles = (element: HTMLElement) => {
    // The phone tab's pill is nearly square, so a circular burst around it
    // reads well. The desktop pill is ~4x wider than tall: a circle either
    // starts inside the pill (invisible) or far above/below it (clipped by
    // the bar). So on desktop the same burst is stretched into an ellipse
    // that hugs the wide pill — bubbles start ~20px outside every edge.
    let d = particleDistances
    let kx = 1
    if (variant === 'top') {
      const ry = element.offsetHeight / 2 - 1
      d = [ry, particleDistances[1]]
      kx = (element.offsetWidth / 2 + 4) / ry
    }
    const r = particleR
    const bubbleTime = animationTime * 2 + timeVariance
    element.style.setProperty('--time', `${bubbleTime}ms`)

    for (let i = 0; i < particleCount; i++) {
      const t = animationTime * 2 + noise(timeVariance * 2)
      const p = createParticle(i, t, d, r)
      p.start[0] *= kx
      p.end[0] *= kx
      // The swirl rotates each offset; on the stretched desktop ellipse that
      // would turn sideways bubbles vertical and clip them, so keep it small.
      if (variant === 'top') {
        p.rotate *= 0.15
        p.scale *= 0.8 // desktop: a little smaller and fewer than the phone tab bar
      }
      element.classList.remove('active')

      const outer = window.setTimeout(() => {
        const particle = document.createElement('span')
        const point = document.createElement('span')
        particle.classList.add('gn-particle')
        particle.style.setProperty('--start-x', `${p.start[0]}px`)
        particle.style.setProperty('--start-y', `${p.start[1]}px`)
        particle.style.setProperty('--end-x', `${p.end[0]}px`)
        particle.style.setProperty('--end-y', `${p.end[1]}px`)
        particle.style.setProperty('--time', `${p.time}ms`)
        particle.style.setProperty('--scale', `${p.scale}`)
        particle.style.setProperty('--color', `var(--color-${p.color}, white)`)
        particle.style.setProperty('--rotate', `${p.rotate}deg`)

        point.classList.add('gn-point')
        particle.appendChild(point)
        element.appendChild(particle)
        requestAnimationFrame(() => element.classList.add('active'))
        const inner = window.setTimeout(() => {
          if (particle.parentNode === element) element.removeChild(particle)
        }, t)
        timers.current.push(inner)
      }, 30)
      timers.current.push(outer)
    }
  }

  const updateEffectPosition = useCallback((element: HTMLElement | null) => {
    const filter = filterRef.current
    const container = containerRef.current
    if (!filter || !container) return
    if (!element) { filter.style.opacity = '0'; return }
    const containerRect = container.getBoundingClientRect()
    const pos = element.getBoundingClientRect()
    Object.assign(filter.style, {
      opacity: '1',
      left: `${pos.x - containerRect.x}px`,
      top: `${pos.y - containerRect.y}px`,
      width: `${pos.width}px`,
      height: `${pos.height}px`,
    })
  }, [])

  const activeLi = () =>
    (activeIndex >= 0 ? navRef.current?.querySelectorAll('li')[activeIndex] : null) as HTMLElement | null

  // Position the effect under the current item, and burst only on a change.
  useLayoutEffect(() => {
    const li = activeLi()
    updateEffectPosition(li)
    const changed = prevIndex.current !== activeIndex
    prevIndex.current = activeIndex
    const filter = filterRef.current
    if (!changed || !li || !filter) {
      if (li && filter) filter.classList.add('active')
      return
    }
    filter.querySelectorAll('.gn-particle').forEach((p) => p.remove())
    // Skip the burst when this copy of the nav isn't on screen (the desktop
    // pill and the phone tab bar both exist; CSS hides one of them).
    const hidden = !containerRef.current || containerRef.current.offsetParent === null
    if (reducedMotion() || hidden) { filter.classList.add('active'); return }
    makeParticles(filter)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const ro = new ResizeObserver(() => updateEffectPosition(activeLi()))
    ro.observe(container)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, updateEffectPosition])

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), [])

  return (
    <div className={`gooey-nav-container gn-${variant} ${className}`.trim()} ref={containerRef}>
      <nav aria-label={ariaLabel}>
        <ul ref={navRef}>
          {items.map((item, index) => (
            <li key={item.href} className={activeIndex === index ? 'active' : ''}>
              <a
                href={item.href}
                aria-current={activeIndex === index ? 'page' : undefined}
                onClick={(e) => { e.preventDefault(); onSelect(index) }}
              >
                {item.icon}
                <span className="gn-label">{item.label}</span>
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <span className="effect filter" ref={filterRef} aria-hidden="true" />
    </div>
  )
}
