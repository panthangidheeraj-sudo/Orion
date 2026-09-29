import { useState, type ReactNode } from 'react'
import { Icon, MoonMark } from '../ui/Icon'
import { Cap, Chip, SettingRow, Status, Switch } from '../ui/bits'
import { useStore } from '../app/store'
import { systemCapabilities, type Capability } from '../app/capabilities'
import { getAccessKey, setAccessKey } from '../app/api'

const VERSION = '1.0.0'
const BUILD = '2026.09.19 · sd-arm64'

type CategoryId = 'profile' | 'account' | 'appearance' | 'privacy' | 'status' | 'about'

const CATEGORIES: { id: CategoryId; label: string; icon: string }[] = [
  { id: 'profile', label: 'Profile', icon: 'user' },
  { id: 'account', label: 'Account', icon: 'lock' },
  { id: 'appearance', label: 'Appearance', icon: 'moon' },
  { id: 'privacy', label: 'AI access & privacy', icon: 'eye' },
  { id: 'status', label: 'System status', icon: 'cpu' },
  { id: 'about', label: 'Application', icon: 'info' },
]

const CAP_ICON: Record<Capability['key'], string> = {
  backend: 'layers', ai: 'cpu', camera: 'cam', voice: 'mic', web: 'wifioff',
}

export function Settings() {
  const { profile, setProfile, access, setAccess, prefs, setPrefs, files, toast, backend, refreshBackend } = useStore()
  const [active, setActive] = useState<CategoryId>('profile')
  const [keyDraft, setKeyDraft] = useState(() => getAccessKey())

  const field = (key: keyof typeof profile, label: string, placeholder: string) => (
    <label className="field" key={key}>
      <Cap>{label}</Cap>
      <input
        value={profile[key]}
        placeholder={placeholder}
        onChange={(e) => setProfile({ ...profile, [key]: e.target.value })}
      />
    </label>
  )

  const panel: Record<CategoryId, ReactNode> = {
    profile: (
      <>
        <h2>Profile</h2>
        <p className="lead">Used for report headers and to pitch the assistant’s guidance at your level.</p>
        <div className="profile-top">
          <span className="profile-avatar" aria-hidden="true">
            {profile.name.trim()
              ? profile.name.trim().split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()
              : <Icon name="user" size={26} stroke="var(--vf-text-2)" width={1.6} />}
          </span>
          <div className="profile-fields">
            <div className="field-row">
              {field('name', 'Full name', 'Your name')}
              {field('age', 'Age', 'Optional')}
            </div>
            {field('profession', 'Profession', 'e.g. Field service technician — rotating equipment')}
            <div className="field-row">
              {field('experience', 'Experience', 'e.g. 3 years')}
              {field('site', 'Site / employer', 'Appears on report headers')}
            </div>
          </div>
        </div>
      </>
    ),
    account: (
      <>
        <h2>Account</h2>
        <p className="lead">How you sign in.</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', background: 'var(--vf-track)', border: '1px solid var(--vf-border)', borderRadius: 13, marginBottom: 12 }}>
          <Icon name="lock" size={19} stroke="var(--vf-ok)" width={1.7} />
          <div style={{ flex: 1 }}>
            <b style={{ fontSize: 13.5 }}>Local profile</b>
            <div style={{ fontSize: 12, color: 'var(--vf-muted)', marginTop: 2 }}>Stored on this device · no account required</div>
          </div>
          <Chip icon="check" tone="ok" size="sm">Active</Chip>
        </div>
        <button type="button" className="btn wide" disabled>
          <Icon name="google" size={18} stroke="var(--vf-muted)" />
          Continue with Google
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <Icon name="clock" size={14} stroke="var(--vf-muted)" width={1.8} />
          <span style={{ fontSize: 12, color: 'var(--vf-muted)' }}>
            Sign-in arrives in a later release — your local profile carries over.
          </span>
        </div>
      </>
    ),
    appearance: (
      <>
        <h2>Appearance</h2>
        <p className="lead">Theme and motion.</p>
        <div style={{ display: 'flex', gap: 12, marginBottom: 6 }}>
          <button type="button" className="theme-opt" aria-pressed={false} onClick={() => toast('Light mode is not in this build', 'The deep-space identity is dark only for now.')}>
            <span className="swatch" style={{ background: 'linear-gradient(160deg,#ffffff,#e6e8ec)' }} />
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="sun" size={16} stroke="var(--vf-text-2)" width={1.8} />
              <b style={{ fontSize: 13.5 }}>Light</b>
            </span>
          </button>
          <button type="button" className="theme-opt" aria-pressed>
            <span className="swatch" style={{ background: 'linear-gradient(160deg,#1a1c20,#000000)' }} />
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="moon" size={16} stroke="var(--vf-text)" width={1.8} />
              <b style={{ fontSize: 13.5 }}>Dark · current</b>
            </span>
          </button>
        </div>
        <SettingRow
          title="Reduce motion"
          detail={
            prefs.reduceMotion
              ? 'The starfield and voice glow are still. Turn this off to bring the motion back.'
              : 'Starfield and voice glow are animating. On by default — turn this on to reduce motion.'
          }
        >
          <Switch on={prefs.reduceMotion} label="Reduce motion" onChange={(v) => setPrefs({ ...prefs, reduceMotion: v })} />
        </SettingRow>
        <SettingRow title="Web search" detail="On by default — used only after your manuals and history come up short">
          <Switch on={prefs.webSearch} label="Web search" onChange={(v) => setPrefs({ ...prefs, webSearch: v })} />
        </SettingRow>
      </>
    ),
    privacy: (
      <>
        <h2>AI access &amp; privacy</h2>
        <p className="lead">Exactly what the assistant can read about you.</p>
        <div style={{ display: 'flex', gap: 11, padding: '13px 15px', background: 'var(--vf-track)', border: '1px solid var(--vf-border)', borderRadius: 13, marginBottom: 6 }}>
          <Icon name="eye" size={18} stroke="var(--vf-text-2)" width={1.8} />
          <span style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--vf-text-2)' }}>
            The assistant reads the fields ticked below so its guidance matches your experience and the
            equipment you work on. Nothing here leaves the device.
          </span>
        </div>
        <SettingRow title="Name and profession" detail="Lets it address you and pitch explanations at your level">
          <Switch on={access.identity} label="Share name and profession" onChange={(v) => setAccess({ ...access, identity: v })} />
        </SettingRow>
        <SettingRow title="Experience level" detail="Shortens routine explanations you already know">
          <Switch on={access.experience} label="Share experience level" onChange={(v) => setAccess({ ...access, experience: v })} />
        </SettingRow>
        <SettingRow title="Age" detail="Not used by the assistant unless you turn this on">
          <Switch on={access.age} label="Share age" onChange={(v) => setAccess({ ...access, age: v })} />
        </SettingRow>
        <SettingRow title="Job and inspection history" detail="Enables “compared with your previous inspection” answers">
          <Switch on={access.history} label="Share job history" onChange={(v) => setAccess({ ...access, history: v })} />
        </SettingRow>
      </>
    ),
    status: (
      <>
        <h2>System status</h2>
        <p className="lead">What is available on this device right now — read from the local
        engine, not assumed.</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {systemCapabilities(backend, prefs.webSearch).map((c) => (
            <div key={c.key} className="status-row">
              <Icon name={CAP_ICON[c.key]} size={19} stroke="var(--vf-text-2)" width={1.7} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <b style={{ fontSize: 13.5 }}>{c.label}</b>
                <Cap style={{ marginTop: 2, overflowWrap: 'anywhere' }}>{c.detail}</Cap>
              </div>
              <Status label="" state={c.state} word={c.word} />
            </div>
          ))}
        </div>
        <form
          className="access-key"
          onSubmit={(e) => {
            e.preventDefault()
            setAccessKey(keyDraft)
            refreshBackend()
            toast(keyDraft.trim() ? 'Access key saved on this device' : 'Access key removed', 'Re-checking the backend…')
          }}
        >
          <label className="field">
            <Cap>Backend access key</Cap>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={keyDraft}
              placeholder={backend.locked ? 'Required by this backend' : 'Only needed if the backend asks for one'}
              onChange={(e) => setKeyDraft(e.target.value)}
            />
          </label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="submit" className="btn">Save key</button>
            <button
              type="button"
              className="btn ghost"
              onClick={() => { refreshBackend(); toast('Re-checking the local engine') }}
            >
              Re-check
            </button>
          </div>
          <Cap style={{ lineHeight: 1.6, textTransform: 'none', letterSpacing: '0.02em' }}>
            Kept in this browser only. It must match VF_ACCESS_TOKEN on the server.
          </Cap>
        </form>
        {backend.online && backend.synthetic && backend.synthetic.length > 0 && (
          <Cap style={{ marginTop: 10, display: 'block', lineHeight: 1.6 }}>
            {backend.synthetic.join(' and ')} {backend.synthetic.length > 1 ? 'are' : 'is'} running a
            deterministic stand-in rather than an exported model. Answers stay evidence-bound, but
            nothing is running on the NPU.
          </Cap>
        )}
      </>
    ),
    about: (
      <>
        <h2>Application</h2>
        <p className="lead">Build information.</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '12px 20px' }}>
          {[
            ['Version', VERSION],
            ['Build', BUILD],
            ['Indexed files', String(files.filter((f) => f.state === 'ready').length)],
            ['Licence', '[YOUR LICENCE]'],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <Cap>{k}</Cap>
              <span className="mono" style={{ fontSize: 12.5 }}>{v}</span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 18 }}>
          <MoonMark size={22} />
          <Cap>Orion</Cap>
        </div>
      </>
    ),
  }

  return (
    <div className="settings-page">
      <section className="panel settings-shell">
        <header className="settings-head">
          <h1>Profile &amp; Settings</h1>
          <Cap>Everything on this page stays on this device</Cap>
        </header>

        <div className="settings-body">
          <nav className="settings-sidebar" aria-label="Settings categories">
            {CATEGORIES.map((c) => (
              <button
                key={c.id}
                type="button"
                className="settings-navitem"
                aria-current={active === c.id ? 'page' : undefined}
                onClick={() => setActive(c.id)}
              >
                <Icon name={c.icon} size={16} stroke={active === c.id ? 'var(--vf-on-invert)' : 'var(--vf-muted)'} width={1.8} />
                <span>{c.label}</span>
              </button>
            ))}
          </nav>

          <div key={active} className="settings-panel vf-enter">
            {panel[active]}
          </div>
        </div>
      </section>
    </div>
  )
}
