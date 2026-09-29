import { useState } from 'react'
import { Composer } from '../ui/Composer'
import { Status } from '../ui/bits'
import { useStore } from '../app/store'
import { useAsk } from '../app/useAsk'
import { systemCapabilities } from '../app/capabilities'
import type { Mode } from '../app/types'
import { Icon } from '../ui/Icon'
import TextPressure from '../ui/TextPressure'

const SUGGESTIONS = [
  { icon: 'gauge', text: 'Diagnose a vibration', prompt: 'The drive end is vibrating and running hot. Where do I start?' },
  { icon: 'text', text: 'Read a nameplate', prompt: 'Read the nameplate and tell me the ratings.' },
  { icon: 'history', text: 'Last inspection', prompt: 'Compare this with the last inspection and tell me if it is getting worse.' },
]

export function Home() {
  const { go, newConversation, files, addFiles, prefs, backend } = useStore()
  const { ask } = useAsk()
  const [mode, setMode] = useState<Mode>('normal')
  const [pending, setPending] = useState<string[]>([])

  // Reflect what is actually available — never a fixed "ready". Every state
  // comes from the backend's own model report or a real browser check.
  const caps = systemCapabilities(backend, prefs.webSearch)

  const start = (text: string) => {
    newConversation()
    ask(text, 'normal', pending)
    setPending([])
    go('chat')
  }

  const attached = files.filter((f) => pending.includes(f.id))

  return (
    <div className="home">
      <div className="home-body">
        <div className="hero-pressure" role="heading" aria-level={1} aria-label="Every fault, seen clearly.">
          <TextPressure as="div" text="Every fault," textColor="rgba(var(--vf-fg-rgb), 0.72)" minFontSize={26} maxFontSize={78} italic={false} />
          <TextPressure as="div" text="seen clearly." textColor="var(--vf-text)" minFontSize={26} maxFontSize={78} italic={false} />
        </div>
        <Composer
          compact
          mode={mode}
          onMode={(m) => {
            setMode(m)
            if (m === 'live') { newConversation('Live inspection'); go('live') }
          }}
          onSend={start}
          attached={attached}
          onAttach={(list) => setPending((p) => [...p, ...addFiles(list).map((f) => f.id)])}
          onDetach={(id) => setPending((p) => p.filter((x) => x !== id))}
          placeholder="New Chat"
        />

        <div className="suggestions vf-stagger">
          {SUGGESTIONS.map((s) => (
            <button key={s.text} type="button" className="suggestion" onClick={() => start(s.prompt)}>
              <Icon name={s.icon} size={14} stroke="rgba(var(--vf-fg-rgb), .55)" />
              {s.text}
            </button>
          ))}
        </div>
      </div>

      <div className="home-foot">
        <div className="strip">
          {caps.map((c) => (
            <span key={c.key} title={c.detail}><Status label={c.label} state={c.state} word={c.word} /></span>
          ))}
        </div>
        <button
          type="button"
          className="cap"
          style={{ background: 'none', border: 0, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 7 }}
          onClick={() => go('onboarding')}
        >
          First run tour <Icon name="chevR" size={13} stroke="var(--vf-muted)" width={1.9} />
        </button>
      </div>
    </div>
  )
}
