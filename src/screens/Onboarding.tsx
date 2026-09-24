import { useState } from 'react'
import { Brandmark, Icon } from '../ui/Icon'
import { Cap, Chip } from '../ui/bits'
import { useStore } from '../app/store'

const STEPS = ['Welcome', 'Normal Mode', 'Live Mode', 'Privacy', 'Your profile'] as const

export function Onboarding() {
  const { go, prefs, setPrefs, profile, setProfile } = useStore()
  const [step, setStep] = useState(0)

  const finish = () => {
    setPrefs({ ...prefs, onboarded: true })
    go('home')
  }

  const body = [
    {
      title: 'A second technician, on your device',
      copy: 'VisionField Copilot looks at the equipment with you, reads your manuals, and reasons through the fault the way an experienced colleague would. No cloud, no account.',
      points: ['Runs on the device’s NPU', 'Works with no signal', 'Nothing is uploaded'],
    },
    {
      title: 'Describe it, or show it',
      copy: 'In Normal Mode you type or dictate. Attach a photo, a datasheet or a maintenance PDF and answers come back with page numbers, not guesses.',
      points: ['Structured answers: observed, inferred, next check', 'Every claim cites its source', 'Uncertainty is stated, never hidden'],
    },
    {
      title: 'Show it the machine, talk it through',
      copy: 'In Live Mode the camera takes over the screen. Speak normally — VisionField answers out loud, marks what it can see, and reads nameplates as you move.',
      points: ['Everything stays on the device', 'Live and Normal are one conversation', 'Tap any detected part to focus the analysis'],
    },
    {
      title: 'It asks before it looks',
      copy: 'The camera and microphone are requested in context, with the reason stated. Declining is a supported state — the rest of the product keeps working.',
      points: ['Camera: inspecting equipment in Live Mode', 'Microphone: asking questions with your hands full', 'Both revocable in Profile & Settings'],
    },
    {
      title: 'Tell it who it is helping',
      copy: 'Your trade and experience change how much VisionField explains. You can edit or delete any of this later.',
      points: [],
    },
  ][step]

  return (
    <div className="onb">
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
        <Brandmark size={30} />
        <div className="steps">
          {STEPS.map((s, i) => (
            <div key={s} className={`s ${i === step ? 'now' : i < step ? 'done' : ''}`}>
              <span className="n">{i < step ? '✓' : i + 1}</span>
              <span>{s}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="onb-card">
        <Cap style={{ marginBottom: 10 }}>Step {step + 1} of {STEPS.length} · {STEPS[step]}</Cap>
        <h2>{body.title}</h2>
        <p className="copy">{body.copy}</p>

        {body.points.length > 0 && (
          <ul className="onb-list">
            {body.points.map((p) => (
              <li key={p}>
                <Icon name="check" size={16} stroke="var(--vf-ok)" width={2.1} />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        )}

        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 18, maxWidth: 460 }}>
            <label className="field">
              <Cap>Full name</Cap>
              <input value={profile.name} placeholder="Your name" onChange={(e) => setProfile({ ...profile, name: e.target.value })} />
            </label>
            <label className="field">
              <Cap>Profession</Cap>
              <input value={profile.profession} placeholder="e.g. Field service technician" onChange={(e) => setProfile({ ...profile, profession: e.target.value })} />
            </label>
            <label className="field">
              <Cap>Years of experience</Cap>
              <input value={profile.experience} placeholder="Optional" onChange={(e) => setProfile({ ...profile, experience: e.target.value })} />
            </label>
            <div style={{ display: 'flex', gap: 10, padding: '12px 13px', background: 'var(--vf-inset)', border: '1px solid var(--vf-border)', borderRadius: 12 }}>
              <Icon name="lock" size={17} stroke="var(--vf-ok)" width={1.8} />
              <span style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--vf-text-2)' }}>
                Stored on this device only. Nothing is uploaded and no account is needed.
              </span>
            </div>
          </div>
        )}

        {step === 2 && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Chip icon="cam" size="sm">Camera permission next</Chip>
            <Chip icon="clock" size="sm">~40 seconds</Chip>
          </div>
        )}

        <div className="onb-foot">
          <button type="button" className="btn ghost sm" onClick={finish}>Skip the tour</button>
          <span style={{ flex: 1 }} />
          {step > 0 && (
            <button type="button" className="btn ghost" onClick={() => setStep((s) => s - 1)}>Back</button>
          )}
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn primary" onClick={() => setStep((s) => s + 1)}>
              Continue
              <Icon name="chevR" size={17} stroke="var(--vf-on-invert)" width={1.9} />
            </button>
          ) : (
            <button type="button" className="btn primary" onClick={finish}>
              <Icon name="check" size={17} stroke="var(--vf-on-invert)" width={2} />
              Finish setup
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
