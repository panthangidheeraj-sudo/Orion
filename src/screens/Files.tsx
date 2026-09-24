import { useRef, useState } from 'react'
import { Icon } from '../ui/Icon'
import { Cap, Chip, Modal } from '../ui/bits'
import { useStore } from '../app/store'
import { fmtBytes, fmtDate } from '../app/util'
import type { VFile } from '../app/types'

const TABS = ['All files', 'Manuals', 'Photos', 'Other'] as const

function matches(f: VFile, tab: (typeof TABS)[number]) {
  if (tab === 'All files') return true
  if (tab === 'Manuals') return f.kind === 'pdf'
  if (tab === 'Photos') return f.kind === 'image'
  return f.kind !== 'pdf' && f.kind !== 'image'
}

function stateChip(f: VFile) {
  if (f.state === 'ready') return <Chip icon="check" tone="ok" size="sm">Ready</Chip>
  if (f.state === 'failed') return <Chip icon="warn" tone="danger" size="sm">Unsupported</Chip>
  const word = f.state === 'uploading' ? 'Uploading' : f.state === 'reading' ? 'Reading' : 'Indexing'
  return <Chip icon="layers" size="sm">{word}</Chip>
}

export function Files() {
  const { files, addFiles, removeFile, go, toast, active, attachToActive } = useStore()
  const [tab, setTab] = useState<(typeof TABS)[number]>('All files')
  const [confirm, setConfirm] = useState<VFile | null>(null)
  const picker = useRef<HTMLInputElement | null>(null)

  const shown = files.filter((f) => matches(f, tab))
  const indexed = files.filter((f) => f.state === 'ready')
  const bytes = files.reduce((n, f) => n + f.size, 0)

  return (
    <section className="panel sheet-page">
      <div className="sheet-head">
        <div>
          <h2>Files &amp; documents</h2>
          <span className="sub">Manuals, schematics and captures available to the assistant</span>
        </div>
        <span style={{ flex: 1 }} />
        <input
          ref={picker} type="file" multiple hidden
          accept="image/*,application/pdf,text/plain,.md,.csv"
          onChange={(e) => {
            if (e.target.files?.length) {
              const made = addFiles(e.target.files)
              if (active) attachToActive(made.map((f) => f.id))
              toast(`${made.length} file${made.length > 1 ? 's' : ''} added`, 'Indexing runs on the NPU, on this device.')
            }
            e.target.value = ''
          }}
        />
        <button type="button" className="btn primary sm" onClick={() => picker.current?.click()}>
          <Icon name="plus" size={16} stroke="var(--vf-on-invert)" width={1.9} />
          Add files
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, padding: '14px 22px', borderBottom: '1px solid var(--vf-track)', flexWrap: 'wrap' }}>
        {TABS.map((t) => (
          <button
            key={t} type="button" aria-pressed={tab === t}
            className={tab === t ? 'btn sm primary' : 'btn sm ghost'}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="sheet-body">
        {shown.length === 0 ? (
          <div className="empty" style={{ padding: '60px 20px' }}>
            <Icon name="folder" size={34} stroke="var(--vf-text-2)" width={1.4} />
            <h2 style={{ fontSize: 22 }}>No files here yet</h2>
            <p>Add a manual, a datasheet or a schematic and VisionField will cite it by page number.</p>
            <button type="button" className="btn primary" onClick={() => picker.current?.click()}>
              <Icon name="plus" size={17} stroke="var(--vf-on-invert)" />Add files
            </button>
          </div>
        ) : (
          <div className="grid-files">
            {shown.map((f) => (
              <div key={f.id} className="filecard">
                <button
                  type="button"
                  style={{ all: 'unset', cursor: 'pointer', display: 'block', width: '100%' }}
                  onClick={() => (f.kind === 'pdf' ? go('doc', { doc: f.id }) : undefined)}
                >
                  <span className="prev">
                    {f.url && f.kind === 'image'
                      ? <img src={f.url} alt={f.name} />
                      : <Icon name={f.kind === 'pdf' ? 'file' : 'text'} size={34} stroke="var(--vf-border-strong)" width={1.3} />}
                    <span className="tag">{stateChip(f)}</span>
                  </span>
                  <span className="info">
                    <b>{f.name}</b>
                    <span className="mono" style={{ display: 'block', fontSize: 10, color: 'var(--vf-muted)', marginTop: 6 }}>
                      {f.pages ? `${f.pages} pages · ` : ''}{fmtBytes(f.size)} · {fmtDate(f.addedAt)}
                    </span>
                    {(f.state === 'uploading' || f.state === 'reading' || f.state === 'indexing') && (
                      <span className="meter" style={{ display: 'block', marginTop: 10 }}>
                        <i style={{ width: `${f.progress}%` }} />
                      </span>
                    )}
                    {f.note && (
                      <span style={{ display: 'block', fontSize: 11.5, color: 'var(--vf-danger)', marginTop: 8, lineHeight: 1.45 }}>
                        {f.note}
                      </span>
                    )}
                  </span>
                </button>
                <div style={{ display: 'flex', gap: 6, padding: '0 13px 13px' }}>
                  {f.kind === 'pdf' && (
                    <button type="button" className="btn ghost sm grow" onClick={() => go('doc', { doc: f.id })}>
                      <Icon name="eye" size={15} stroke="var(--vf-text-2)" />Open
                    </button>
                  )}
                  <button type="button" className="btn ghost sm" aria-label={`Remove ${f.name}`} onClick={() => setConfirm(f)}>
                    <Icon name="trash" size={15} stroke="var(--vf-danger)" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '13px 22px', borderTop: '1px solid var(--vf-border)', background: 'var(--vf-inset)', flexWrap: 'wrap' }}>
        <Icon name="cpu" size={15} stroke="var(--vf-muted)" width={1.7} />
        <Cap>{indexed.length} indexed · {fmtBytes(bytes)}</Cap>
        <span style={{ flex: 1 }} />
        <Cap>Embeddings stored locally</Cap>
      </div>

      {confirm && (
        <Modal
          tone="danger"
          title={`Remove “${confirm.name}”?`}
          onClose={() => setConfirm(null)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setConfirm(null)}>Keep file</button>
              <button
                type="button" className="btn dangerf"
                onClick={() => { removeFile(confirm.id); toast('File removed', 'Its index entries went with it.'); setConfirm(null) }}
              >
                Remove
              </button>
            </>
          }
        >
          <p>
            This deletes the file and its index from this device. Conversations that cited it keep their answers,
            but the page links will stop resolving.
          </p>
        </Modal>
      )}
    </section>
  )
}
