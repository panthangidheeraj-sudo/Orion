import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { Icon } from './Icon'
import { Spinner } from './bits'
import { useStore } from '../app/store'
import type { Mode, VFile } from '../app/types'
import { fmtBytes } from '../app/util'
import { listen, speechSupported } from '../app/speech'

const STATE_WORD: Record<VFile['state'], string> = {
  uploading: 'Uploading',
  reading: 'Reading document',
  indexing: 'Indexing pages',
  ready: 'Ready',
  failed: 'Failed',
}

function stateColour(s: VFile['state']) {
  if (s === 'ready') return 'var(--vf-ok)'
  if (s === 'failed') return 'var(--vf-danger)'
  return 'var(--vf-text-2)'
}

export function FileChip({ file, onRemove }: { file: VFile; onRemove?: () => void }) {
  return (
    <div className="filechip">
      <span className="thumb">
        {file.url && file.kind === 'image'
          ? <img src={file.url} alt="" />
          : <Icon name={file.kind === 'pdf' ? 'file' : file.kind === 'text' ? 'text' : 'layers'} size={16} stroke="var(--vf-text-2)" />}
      </span>
      <span className="meta">
        <span className="name">{file.name}</span>
        <span className="state" style={{ color: stateColour(file.state) }}>
          {STATE_WORD[file.state]}{file.state === 'ready' && file.pages && file.kind !== 'image' ? ` · ${file.pages} pages` : ''}
          {file.state === 'ready' && (!file.pages || file.kind === 'image') ? ` · ${fmtBytes(file.size)}` : ''}
        </span>
        {file.state === 'failed' && file.note && (
          <span className="reason" title={file.note}>{file.note}</span>
        )}
      </span>
      {onRemove && (
        <button type="button" className="ibtn plain sm" aria-label={`Remove ${file.name}`} onClick={onRemove}>
          <Icon name="x" size={14} width={1.9} />
        </button>
      )}
    </div>
  )
}

export function Composer({
  placeholder = 'New Chat',
  mode,
  onMode,
  onSend,
  busy,
  onStop,
  attached,
  onAttach,
  onDetach,
  narrow,
  compact,
  autoFocus,
}: {
  placeholder?: string
  mode: Mode
  onMode: (m: Mode) => void
  onSend: (text: string) => void
  busy?: boolean
  onStop?: () => void
  attached: VFile[]
  onAttach: (files: FileList) => void
  onDetach: (id: string) => void
  narrow?: boolean
  compact?: boolean
  autoFocus?: boolean
}) {
  const { prefs, toast } = useStore()
  const [value, setValue] = useState('')
  const [dictating, setDictating] = useState(false)
  const ta = useRef<HTMLTextAreaElement | null>(null)
  const picker = useRef<HTMLInputElement | null>(null)
  const rec = useRef<{ stop: () => void } | null>(null)

  useEffect(() => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(168, el.scrollHeight)}px`
  }, [value])

  useEffect(() => () => rec.current?.stop(), [])

  /** Keep focus in the text field when a composer button is tapped. On a
   * phone, a focus change closes the keyboard and reflows the page between
   * touch-down and touch-up, and the tap then misses the button. */
  const keepFocus = (e: ReactMouseEvent) => e.preventDefault()

  const send = () => {
    const t = value.trim()
    if (!t || busy) return
    onSend(t)
    setValue('')
  }

  const toggleDictation = () => {
    if (dictating) {
      rec.current?.stop()
      rec.current = null
      setDictating(false)
      return
    }
    if (!speechSupported()) {
      toast('Voice input is unavailable', 'This browser has no speech recognition. Typing still works.')
      return
    }
    const l = listen(
      (text, final) => { if (final) setValue((v) => (v ? `${v} ${text}` : text)) },
      (reason) => {
        setDictating(false)
        if (reason !== 'aborted') toast('Voice input stopped', reason === 'not-allowed' ? 'Microphone permission was denied.' : 'Speech recognition ended.')
      },
    )
    if (l) { rec.current = l; setDictating(true) }
  }

  return (
    <form
      className={`composer${narrow ? ' narrow' : ''}${compact ? ' compact' : ''}`}
      onSubmit={(e) => { e.preventDefault(); send() }}
    >
      {!prefs.webSearch && mode === 'normal' && attached.some((f) => f.state === 'failed') && (
        <div className="notice error" style={{ margin: '0 6px 4px' }}>
          <Icon name="warn" size={18} stroke="var(--vf-danger)" width={1.8} />
          <div>
            <div className="title">One file could not be attached</div>
            <div className="text">
              {attached.find((f) => f.state === 'failed')?.note
                ?? 'Export it as a PDF, PNG, JPG or TXT and attach it again.'}
            </div>
          </div>
        </div>
      )}

      {attached.length > 0 && (
        <div className="attachments">
          {attached.map((f) => <FileChip key={f.id} file={f} onRemove={() => onDetach(f.id)} />)}
        </div>
      )}

      <label htmlFor="vf-composer" className="vf-sr">Ask Orion</label>
      <textarea
        id="vf-composer"
        ref={ta}
        rows={1}
        value={value}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
        }}
      />

      <div className="composer-row">
        <div className="composer-left">
          <input
            ref={picker} type="file" multiple hidden
            accept="image/*,application/pdf,text/plain,.md,.csv"
            onChange={(e) => { if (e.target.files?.length) onAttach(e.target.files); e.target.value = '' }}
          />
          <button
            type="button" className="ibtn" aria-label="Add photo, capture or document"
            onMouseDown={keepFocus}
            onClick={() => picker.current?.click()}
          >
            <Icon name="plus" size={17} width={2} />
          </button>
        </div>

        <div className="composer-right">
          {busy ? (
            <>
              <span className="composer-hint" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <Spinner /> Working
              </span>
              <button type="button" className="ibtn" aria-label="Stop generating" onClick={onStop}>
                <Icon name="stop" size={16} width={1.9} />
              </button>
            </>
          ) : (
            <>
              <div className="modetoggle" role="group" aria-label="Conversation mode">
                <button type="button" aria-label="Normal mode" aria-pressed={mode === 'normal'} onClick={() => onMode('normal')}>
                  <Icon name="chat" size={13} stroke={mode === 'normal' ? 'var(--vf-text)' : 'var(--vf-muted)'} width={1.8} />
                  <span className="mt-label">Normal</span>
                </button>
                <button type="button" aria-label="Live mode" aria-pressed={mode === 'live'} onClick={() => onMode('live')}>
                  <Icon name="cam" size={13} stroke={mode === 'live' ? 'var(--vf-text)' : 'var(--vf-muted)'} width={1.8} />
                  <span className="mt-label">Live</span>
                </button>
              </div>
              <button
                type="button"
                className={dictating ? 'ibtn rec' : 'ibtn'}
                aria-label={dictating ? 'Stop voice input' : 'Voice input'}
                aria-pressed={dictating}
                onMouseDown={keepFocus}
                onClick={toggleDictation}
              >
                <Icon name="mic" size={16} />
              </button>
              <button type="submit" className="ibtn key" aria-label="Send message" disabled={!value.trim()} onMouseDown={keepFocus}>
                <Icon name="arrowup" size={17} width={2.1} />
              </button>
            </>
          )}
        </div>
      </div>

      {dictating && (
        <div className="composer-hint" style={{ padding: '0 6px', color: 'var(--vf-text)' }}>
          Listening — speak, then tap the microphone again.
        </div>
      )}
    </form>
  )
}
