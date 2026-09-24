import { Icon, Brandmark } from '../ui/Icon'
import { Cap, Chip, SettingRow, Status, Switch } from '../ui/bits'
import { useStore } from '../app/store'
import type { BackendInfo } from '../app/api'

const VERSION = '1.0.0'
const BUILD = '2026.09.19 · sd-arm64'

type Row = readonly [string, string, string, 'ready' | 'busy' | 'off' | 'error', string?]

/**
 * Report what the engine actually said about itself.
 *
 * The old version of this panel claimed "Local AI — ready" unconditionally.
 * With a real backend that claim has to be earned: it now reflects whether the
 * service is running, which provider answered, and whether the NPU is genuinely
 * in play.
 */
function engineRows(backend: BackendInfo, webSearch: boolean): Row[] {
  const model = backend.model
  const engine: Row = !backend.online
    ? ['cpu', 'Local engine', 'Not running — answers come from the built-in demo responder', 'error']
    : model
      ? [
          'cpu',
          'Local engine',
          model.synthetic
            ? `${model.model_id} — deterministic stand-in, no model exported yet`
            : `${model.model_id} on ${model.accelerator.toUpperCase()}${model.npu ? ' (NPU)' : ''}`,
          model.synthetic ? 'busy' : 'ready',
          model.synthetic ? 'Stand-in' : undefined,
        ]
      : ['cpu', 'Local engine', 'Running, but no reasoning model is loaded', 'error']

  const camera: Row = navigator.mediaDevices
    ? ['cam', 'Camera', 'Available in this browser', 'ready']
    : ['cam', 'Camera', 'Not available in this browser', 'error']

  const speech: Row = backend.ready?.includes('stt')
    ? ['mic', 'Voice', 'On-device speech recognition', 'ready']
    : ['mic', 'Voice', 'Browser speech recognition — no local Whisper export', 'busy', 'Browser']

  const web: Row = webSearch
    ? ['wifioff', 'Web research', 'Enabled — used only after manuals and memory', 'ready']
    : ['wifioff', 'Web research', 'Turned off — manuals and memory only', 'off']

  return [engine, camera, speech, web]
}

export function Settings() {
  const { profile, setProfile, access, setAccess, prefs, setPrefs, files, toast, backend, refreshBackend } = useStore()

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

  return (
    <div className="settings-page">
      <section className="panel settings-shell">
        <header className="settings-head">
          <h1>Profile &amp; Settings</h1>
          <Cap>Everything on this page stays on this device</Cap>
        </header>

        <div className="settings-cols">
          <div className="settings-col">
            <section className="minicard">
            <h2>Profile</h2>
            <p className="lead">Used for report headers and to pitch the assistant’s guidance at your level.</p>
            <div style={{ display: 'flex', gap: 22, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <span
                style={{
                  display: 'grid', placeItems: 'center', width: 88, height: 88, flex: 'none',
                  borderRadius: 24, background: 'linear-gradient(150deg,#33373D,#1A1C20)',
                  border: '1px solid var(--vf-border-strong)', fontFamily: 'var(--vf-mono)', fontSize: 24,
                }}
              >
                {(profile.name || 'VF').split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()}
              </span>
              <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 14 }}>
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
            </section>

            <section className="minicard">
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
            </section>

            <section className="minicard">
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
                  : 'Starfield and voice glow are animating. Defaults to your system setting on first run.'
              }
            >
              <Switch on={prefs.reduceMotion} label="Reduce motion" onChange={(v) => setPrefs({ ...prefs, reduceMotion: v })} />
            </SettingRow>
            <SettingRow title="Web search" detail="Off by default — answers come from your manuals and history">
              <Switch on={prefs.webSearch} label="Web search" onChange={(v) => setPrefs({ ...prefs, webSearch: v })} />
            </SettingRow>
            </section>
          </div>

          <div className="settings-col">
            <section className="minicard">
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
            </section>

            <section className="minicard">
            <h2>System status</h2>
            <p className="lead">What is available on this device right now — read from the local
            engine, not assumed.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {(engineRows(backend, prefs.webSearch)).map(([icon, name, detail, state, word]) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 15px', background: 'var(--vf-track)', border: '1px solid var(--vf-border)', borderRadius: 13 }}>
                  <Icon name={icon} size={19} stroke="var(--vf-text-2)" width={1.7} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <b style={{ fontSize: 13.5 }}>{name}</b>
                    <Cap style={{ marginTop: 2 }}>{detail}</Cap>
                  </div>
                  <Status label="" state={state} word={word} />
                </div>
              ))}
            </div>
            <button
              type="button"
              className="btn ghost"
              style={{ marginTop: 12 }}
              onClick={() => { refreshBackend(); toast('Re-checking the local engine') }}
            >
              Re-check
            </button>
            {backend.online && backend.synthetic && backend.synthetic.length > 0 && (
              <Cap style={{ marginTop: 10, display: 'block', lineHeight: 1.6 }}>
                {backend.synthetic.join(' and ')} {backend.synthetic.length > 1 ? 'are' : 'is'} running a
                deterministic stand-in rather than an exported model. Answers stay evidence-bound, but
                nothing is running on the NPU.
              </Cap>
            )}
            </section>

            <section className="minicard">
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
              <Brandmark size={22} />
              <Cap>VisionField Copilot</Cap>
            </div>
            </section>
          </div>
        </div>
      </section>
    </div>
  )
}
