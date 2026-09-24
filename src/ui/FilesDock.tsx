import { useState } from 'react'
import { Icon } from './Icon'
import type { VFile } from '../app/types'
import { fmtBytes } from '../app/util'

const WORD: Record<VFile['state'], string> = {
  uploading: 'Uploading',
  reading: 'Reading',
  indexing: 'Indexing',
  ready: 'Ready',
  failed: 'Failed',
}

function tone(s: VFile['state']) {
  if (s === 'ready') return 'var(--vf-ok)'
  if (s === 'failed') return 'var(--vf-danger)'
  return 'var(--vf-text-2)'
}

/**
 * A small card docked to the top right of the conversation. Collapsed it is
 * just a count; opened it lists what the assistant can currently read, and
 * hands off to the full Files page.
 */
export function FilesDock({
  files, onOpen, onManage, onReport, onAdd,
}: {
  files: VFile[]
  onOpen: (f: VFile) => void
  onManage: () => void
  onReport: () => void
  onAdd: () => void
}) {
  const [open, setOpen] = useState(false)
  const busy = files.some((f) => f.state !== 'ready' && f.state !== 'failed')

  return (
    <aside className={open ? 'filesdock open' : 'filesdock'} aria-label="Files in this conversation">
      <button
        type="button"
        className="filesdock-head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="folder" size={15} stroke="var(--vf-text-2)" />
        <span className="ttl">Files</span>
        {busy && <span className="pip" aria-label="Indexing" />}
        <span className="count">{files.length}</span>
        <Icon name="chevD" size={15} stroke="var(--vf-muted)" className={open ? 'flip' : undefined} />
      </button>

      {open && (
        <div className="filesdock-body">
          {files.length === 0 ? (
            <p className="filesdock-empty">
              Nothing attached yet. Add a manual or a photo and answers will cite it by page.
            </p>
          ) : (
            files.map((f) => (
              <button key={f.id} type="button" className="filesdock-row" onClick={() => onOpen(f)}>
                <Icon
                  name={f.kind === 'pdf' ? 'file' : f.kind === 'image' ? 'cam' : 'text'}
                  size={14}
                  stroke="var(--vf-muted)"
                />
                <span className="nm">{f.name}</span>
                <span className="st" style={{ color: tone(f.state) }}>
                  {f.state === 'ready' ? (f.pages ? `${f.pages}p` : fmtBytes(f.size)) : WORD[f.state]}
                </span>
              </button>
            ))
          )}

          <div className="filesdock-foot">
            <button type="button" className="btn ghost sm grow" onClick={onAdd}>
              <Icon name="plus" size={14} stroke="var(--vf-text-2)" width={2} />
              Add
            </button>
            <button type="button" className="btn ghost sm grow" onClick={onManage}>
              <Icon name="folder" size={14} stroke="var(--vf-text-2)" />
              Manage
            </button>
            <button type="button" className="btn ghost sm grow" onClick={onReport}>
              <Icon name="book" size={14} stroke="var(--vf-text-2)" />
              Report
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}
