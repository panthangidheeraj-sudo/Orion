import { useMemo, useState } from 'react'
import { Icon } from '../ui/Icon'
import { Cap, Chip, Modal } from '../ui/bits'
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

export function Convo() {
  const {
    conversations, activeId, openConversation, newConversation,
    deleteConversation, files, go, toast,
  } = useStore()
  const [query, setQuery] = useState('')
  const [confirm, setConfirm] = useState<Conversation | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const sorted = [...conversations].sort((a, b) => b.openedAt - a.openedAt)
    if (!q) return sorted
    return sorted.filter(
      (c) => c.title.toLowerCase().includes(q) || c.messages.some((m) => (m.text ?? '').toLowerCase().includes(q)),
    )
  }, [conversations, query])

  const open = (id: string) => { openConversation(id); go('chat') }

  return (
    <section className="panel sheet-page">
      <div className="sheet-head">
        <div>
          <h2>Conversations</h2>
          <span className="sub">
            {conversations.length} stored on this device · nothing synced
          </span>
        </div>
        <span style={{ flex: 1 }} />
        <div className="search" style={{ width: 280, maxWidth: '100%' }}>
          <Icon name="search" size={16} stroke="var(--vf-muted)" width={1.8} />
          <input
            value={query} placeholder="Search conversations"
            aria-label="Search conversations" onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button type="button" className="ibtn plain sm" aria-label="Clear search" onClick={() => setQuery('')}>
              <Icon name="x" size={14} width={1.8} />
            </button>
          )}
        </div>
        <button
          type="button" className="btn primary sm"
          onClick={() => { newConversation(); go('chat') }}
        >
          <Icon name="plus" size={15} stroke="var(--vf-on-invert)" width={2} />
          New conversation
        </button>
      </div>

      <div className="sheet-body">
        {filtered.length === 0 && (
          <div className="empty" style={{ padding: '60px 20px' }}>
            <Icon name={query ? 'search' : 'chat'} size={34} stroke="var(--vf-text-2)" width={1.4} />
            <h2 style={{ fontSize: 22 }}>
              {query ? `Nothing matched “${query}”` : 'No conversations yet'}
            </h2>
            <p>
              {query
                ? 'Search looks through titles and transcripts — try a part number or a machine name.'
                : 'Your first inspection will appear here with the date it started and when you last opened it.'}
            </p>
            {query ? (
              <button type="button" className="btn" onClick={() => setQuery('')}>Clear search</button>
            ) : (
              <button type="button" className="btn primary" onClick={() => { newConversation(); go('chat') }}>
                <Icon name="plus" size={17} stroke="var(--vf-on-invert)" width={2} />
                Start a conversation
              </button>
            )}
          </div>
        )}

        {group(filtered).map(([label, items]) => (
          <div key={label}>
            <Cap style={{ padding: '16px 24px 8px' }}>{label}</Cap>
            {items.map((c) => {
              const attached = files.filter((f) => c.fileIds.includes(f.id))
              const live = c.messages.some((m) => m.mode === 'live')
              const last = c.messages[c.messages.length - 1]
              return (
                <div className="convopage-row" key={c.id}>
                  <button type="button" className="hit" onClick={() => open(c.id)}>
                    <span className="main">
                      <span className="ttl">
                        {c.id === activeId && <i className="cur" />}
                        {c.title}
                      </span>
                      <span className="prev">{last?.text ?? 'Structured answer'}</span>
                    </span>

                    <span className="tags">
                      {live && <Chip icon="cam" size="sm">Live session</Chip>}
                      {attached.length > 0 && (
                        <Chip icon="file" size="sm">{attached.length} file{attached.length > 1 ? 's' : ''}</Chip>
                      )}
                    </span>

                    <span className="when mono">{fmtDate(c.startedAt)} · {fmtClock(c.startedAt)}</span>
                    <span className="ago mono">{fmtAgo(c.openedAt)}</span>
                  </button>

                  <button
                    type="button" className="ibtn plain sm"
                    aria-label={`Delete ${c.title}`} onClick={() => setConfirm(c)}
                  >
                    <Icon name="trash" size={16} width={1.7} />
                  </button>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      <div className="sheet-foot">
        <Icon name="lock" size={14} stroke="var(--vf-muted)" width={1.7} />
        <Cap>Transcripts, frames and reports all stay on this device</Cap>
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
    </section>
  )
}
