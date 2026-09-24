import { useEffect, useMemo, useState } from 'react'
import { Icon } from './Icon'
import { Cap, Modal } from './bits'
import { useStore } from '../app/store'
import type { Conversation } from '../app/types'
import { fmtAgo, fmtClock, fmtDate } from '../app/util'

function group(list: Conversation[]) {
  const day = 86_400_000
  const now = Date.now()
  const buckets: Record<string, Conversation[]> = { Today: [], 'This week': [], Earlier: [] }
  list.forEach((c) => {
    const age = now - c.openedAt
    buckets[age < day ? 'Today' : age < 7 * day ? 'This week' : 'Earlier'].push(c)
  })
  return Object.entries(buckets).filter(([, items]) => items.length > 0)
}

/** The conversation list, opened from the Convo item in the navigation. */
export function ConvoMenu({ onClose }: { onClose: () => void }) {
  const { conversations, activeId, openConversation, newConversation, deleteConversation, go, toast } = useStore()
  const [query, setQuery] = useState('')
  const [confirm, setConfirm] = useState<Conversation | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const sorted = [...conversations].sort((a, b) => b.openedAt - a.openedAt)
    if (!q) return sorted
    return sorted.filter(
      (c) => c.title.toLowerCase().includes(q) || c.messages.some((m) => (m.text ?? '').toLowerCase().includes(q)),
    )
  }, [conversations, query])

  const open = (id: string) => { openConversation(id); go('chat'); onClose() }

  return (
    <>
      <div className="convoscrim" role="presentation" onClick={onClose} />
      <div className="convomenu" role="dialog" aria-label="Conversations">
        <div className="convomenu-head">
          <div className="search">
            <Icon name="search" size={16} stroke="var(--vf-muted)" width={1.8} />
            <input
              autoFocus value={query} placeholder="Search conversations"
              aria-label="Search conversations" onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button type="button" className="ibtn plain sm" aria-label="Clear search" onClick={() => setQuery('')}>
                <Icon name="x" size={14} width={1.8} />
              </button>
            )}
          </div>
          <button
            type="button" className="btn primary sm" style={{ flex: 'none' }}
            onClick={() => { newConversation(); go('chat'); onClose() }}
          >
            <Icon name="plus" size={15} stroke="var(--vf-on-invert)" width={2} />
            New
          </button>
        </div>

        <div className="convomenu-list">
          {filtered.length === 0 && (
            <p className="convomenu-empty">
              Nothing matched “{query}”. Search looks through titles and transcripts — try a part number
              or a machine name.
            </p>
          )}
          {group(filtered).map(([label, items]) => (
            <div key={label}>
              <Cap style={{ padding: '12px 10px 5px' }}>{label}</Cap>
              {items.map((c) => (
                <div className="convorow" key={c.id}>
                  <button
                    type="button"
                    className={c.id === activeId ? 'convo-item on' : 'convo-item'}
                    onClick={() => open(c.id)}
                  >
                    <span className="t">
                      {c.id === activeId && <i className="cur" />}
                      <span>{c.title}</span>
                    </span>
                    {c.messages.length > 0 && (
                      <span className="p">{c.messages[c.messages.length - 1].text ?? 'Structured answer'}</span>
                    )}
                    <span className="m">
                      <span>{fmtDate(c.startedAt)} · {fmtClock(c.startedAt)}</span>
                      <span style={{ opacity: 0.45 }}>/</span>
                      <span>{fmtAgo(c.openedAt)}</span>
                    </span>
                  </button>
                  <button
                    type="button" className="ibtn plain sm convodel"
                    aria-label={`Delete ${c.title}`} onClick={() => setConfirm(c)}
                  >
                    <Icon name="trash" size={15} width={1.7} />
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>

        <div className="convomenu-foot">
          <Icon name="lock" size={13} stroke="var(--vf-muted)" width={1.7} />
          <Cap>{conversations.length} stored on this device</Cap>
        </div>
      </div>

      {confirm && (
        <Modal
          tone="danger"
          title={`Delete “${confirm.title}”?`}
          onClose={() => setConfirm(null)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setConfirm(null)}>Keep conversation</button>
              <button
                type="button" className="btn dangerf"
                onClick={() => {
                  deleteConversation(confirm.id)
                  toast('Conversation deleted', 'Its transcript and evidence frames went with it.')
                  setConfirm(null)
                }}
              >
                Delete permanently
              </button>
            </>
          }
        >
          <p>
            This removes the conversation and its transcript from this device. Files stay in your library,
            and any report you already exported is not affected.
          </p>
        </Modal>
      )}
    </>
  )
}
