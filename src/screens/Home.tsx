import { useState } from 'react'
import { Composer } from '../ui/Composer'
import { Status } from '../ui/bits'
import { useStore } from '../app/store'
import { useAsk } from '../app/useAsk'
import type { Mode } from '../app/types'
import { Icon } from '../ui/Icon'

const SUGGESTIONS = [
  { icon: 'gauge', text: 'Diagnose a vibration', prompt: 'The drive end is vibrating and running hot. Where do I start?' },
  { icon: 'text', text: 'Read a nameplate', prompt: 'Read the nameplate and tell me the ratings.' },
  { icon: 'history', text: 'Last inspection', prompt: 'Compare this with the last inspection and tell me if it is getting worse.' },
]

export function Home() {
  const { go, newConversation, files, addFiles, prefs } = useStore()
  const { ask } = useAsk()
  const [mode, setMode] = useState<Mode>('normal')
  const [pending, setPending] = useState<string[]>([])

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
        <h1>Every fault, <b>seen clearly</b>.</h1>
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

        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s.text} type="button" className="suggestion" onClick={() => start(s.prompt)}>
              <Icon name={s.icon} size={14} stroke="rgba(255,255,255,.55)" />
              {s.text}
            </button>
          ))}
        </div>
      </div>

      <div className="home-foot">
        <div className="strip">
          <Status label="Local AI" state="ready" />
          <Status label="Camera" state="ready" />
          <Status label="Voice" state="ready" />
          <Status label="Web search" state={prefs.webSearch ? 'ready' : 'off'} />
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
