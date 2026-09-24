import React from 'react'
import { Icon } from './Icon'
import { cx } from '../app/util'

export const Cap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => (
  <div className="cap" style={style}>{children}</div>
)

export function Chip({
  children, icon, tone = 'neutral', size,
}: {
  children: React.ReactNode
  icon?: string
  tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'glass'
  size?: 'sm'
}) {
  const colour =
    tone === 'ok' ? 'var(--vf-ok)' : tone === 'warn' ? 'var(--vf-warn)' :
    tone === 'danger' ? 'var(--vf-danger)' : 'currentColor'
  return (
    <span className={cx('chip', tone !== 'neutral' && tone, size)}>
      {icon && <Icon name={icon} size={size ? 13 : 14} stroke={colour} width={1.8} />}
      {children}
    </span>
  )
}

/** Status is always shape + word + colour — never colour on its own. */
export function Status({
  label, state, word,
}: {
  label: string
  state: 'ready' | 'busy' | 'off' | 'error'
  /** Overrides the default word, for states the four names describe badly. */
  word?: string
}) {
  const map = {
    ready: { colour: 'var(--vf-ok)', icon: 'check', word: 'Ready' },
    busy: { colour: 'var(--vf-warn)', icon: 'clock', word: 'Loading' },
    off: { colour: 'var(--vf-muted)', icon: 'wifioff', word: 'Disabled' },
    error: { colour: 'var(--vf-danger)', icon: 'warn', word: 'Unavailable' },
  }[state]
  return (
    <span className="status">
      <Icon name={map.icon} size={13} stroke={map.colour} width={1.9} />
      <span>{label}</span>
      <span style={{ color: map.colour }}>{word ?? map.word}</span>
    </span>
  )
}

export function Switch({
  on, onChange, label,
}: {
  on: boolean
  onChange: (next: boolean) => void
  label: string
}) {
  return (
    <button
      type="button" role="switch" aria-checked={on} aria-label={label}
      className="switch" onClick={() => onChange(!on)}
    >
      <i />
    </button>
  )
}

export function SettingRow({
  title, detail, children,
}: {
  title: string
  detail: string
  children: React.ReactNode
}) {
  return (
    <div className="srow">
      <div className="lbl"><b>{title}</b><span>{detail}</span></div>
      {children}
    </div>
  )
}

export function Modal({
  title, children, onClose, actions, tone,
}: {
  title: string
  children: React.ReactNode
  onClose: () => void
  actions: React.ReactNode
  tone?: 'danger'
}) {
  return (
    <div className="scrim" role="presentation" onClick={onClose}>
      <div
        className="modal" role="dialog" aria-modal="true" aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        {tone === 'danger' && (
          <span
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 44, height: 44, borderRadius: 13, marginBottom: 16,
              background: 'rgba(255,122,107,0.12)', border: '1px solid rgba(255,122,107,0.34)',
            }}
          >
            <Icon name="trash" size={21} stroke="var(--vf-danger)" width={1.8} />
          </span>
        )}
        <h3>{title}</h3>
        {children}
        <div className="actions">{actions}</div>
      </div>
    </div>
  )
}

export function Spinner({ size = 15, colour = 'var(--vf-text-2)' }: { size?: number; colour?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className="spin" aria-hidden="true" style={{ flex: 'none' }}>
      <circle cx="12" cy="12" r="8.5" stroke={colour} strokeWidth="2" strokeDasharray="40 14" strokeLinecap="round" />
    </svg>
  )
}
