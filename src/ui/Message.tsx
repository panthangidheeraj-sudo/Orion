import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AiMark, Icon } from './Icon'
import { Chip, Cap, Spinner } from './bits'
import { useStore } from '../app/store'
import type { Message, Section, Step, VFile } from '../app/types'
import { fmtClock } from '../app/util'
import { FileChip } from './Composer'
import { Markdown } from './Markdown'

/** Splits into "word + trailing whitespace" chunks, so revealing a prefix of
 * the array and joining it always lands on a clean word boundary. */
function wordChunks(text?: string): string[] {
  return text ? text.match(/\S+\s*/g) ?? [] : []
}

const REVEAL_CURSOR = (
  <i
    aria-hidden
    style={{
      display: 'inline-block', width: 2, height: '1em', marginLeft: 1, verticalAlign: -3,
      background: 'var(--vf-text)', animation: 'vf-blink 1.1s steps(1) infinite',
    }}
  />
)

/** One heading per kind of finding. The backend sends each finding as its own
 * item; they are grouped here so an answer reads as a few sections with lists,
 * not a log with a label and an icon on every sentence. */
const SECTION_META: Record<Section['kind'], { label: string; order: number; numbered?: boolean }> = {
  observed: { label: 'Observed', order: 0 },
  inferred: { label: 'Interpretation', order: 1 },
  next: { label: 'Next checks', order: 2, numbered: true },
  measure: { label: 'Still to confirm', order: 3 },
  ref: { label: 'From your documents', order: 4 },
}

interface SectionGroup { key: string; kind: Section['kind']; label: string; safety: boolean; idx: number[] }

/** Group item indexes under one heading each — the model's own heading when it
 * gave one, otherwise the kind's label — ordered observed → next checks, with a
 * "Safety" section last. */
function groupSections(sections: Section[] | undefined): SectionGroup[] {
  const groups = new Map<string, SectionGroup>()
  ;(sections ?? []).forEach((s, i) => {
    const label = s.title?.trim() || SECTION_META[s.kind].label
    const key = `${s.kind}|${label.toLowerCase()}`
    const g = groups.get(key)
    if (g) g.idx.push(i)
    else groups.set(key, { key, kind: s.kind, label, safety: /^safety$/i.test(label), idx: [i] })
  })
  const rank = (g: SectionGroup) => (g.safety ? 9 : SECTION_META[g.kind].order)
  return [...groups.values()].sort((a, b) => rank(a) - rank(b))
}

const NOTICE_META = {
  safety: { kind: 'Safety', icon: 'shield', colour: 'var(--vf-warn)' },
  need: { kind: 'To confirm', icon: 'info', colour: 'var(--vf-text)' },
  confirmed: { kind: 'Confirmed finding', icon: 'check', colour: 'var(--vf-ok)' },
  error: { kind: 'Could not complete', icon: 'warn', colour: 'var(--vf-danger)' },
} as const

export function UserMessage({ msg, files }: { msg: Message; files: VFile[] }) {
  const attached = files.filter((f) => msg.attachments?.includes(f.id))
  return (
    <div className="msg-user vf-enter">
      {attached.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {attached.map((f) => <FileChip key={f.id} file={f} />)}
        </div>
      )}
      <div className="bubble">{msg.text}</div>
      <span className="meta">You · {fmtClock(msg.at)}</span>
    </div>
  )
}

/**
 * Running text in an assistant turn.
 *
 * The Message type has always allowed `text`; before this it was only rendered
 * for the user's own turn, so a conversational reply arrived as an empty card.
 * Blank lines in the source become extra space above the next paragraph rather
 * than empty elements, which keeps the rhythm even.
 */
function Prose({ text, chat, cursor }: { text: string; chat: boolean; cursor?: ReactNode }) {
  // Markdown (bold, lists, headings) is rendered, never shown as raw syntax.
  return (
    <div className={`prose${chat ? ' prose-chat' : ''}`}>
      <Markdown text={text} cursor={cursor} />
    </div>
  )
}

export function AssistantMessage({
  msg, onOpenDoc, onFollowUp,
}: {
  msg: Message
  onOpenDoc?: (doc: string, page: number) => void
  onFollowUp?: (text: string) => void
}) {
  const { prefs, peekFreshMessage, consumeFreshMessage } = useStore()
  const notice = msg.notice
  const nm = notice ? NOTICE_META[notice.level] : null
  // The backend's router decided what kind of turn this is; the client only
  // renders it. Anything that isn't a diagnosis is plain prose — and when the
  // safety gate raised a notice, that notice comes first.
  const isChat = msg.kind
    ? msg.kind !== 'diagnosis'
    : Boolean(msg.text) && !msg.sections?.length && !notice && !msg.refs?.length && !msg.evidence?.length
  const noticeFirst = Boolean(notice) && (isChat || Boolean(notice?.first))

  // The reveal plan: text and section prose broken into words (so they type
  // in), everything else counted as a single unit that appears whole once
  // its turn comes. Order matches the render below exactly.
  const plan = useMemo(() => {
    const textWords = wordChunks(msg.text ?? msg.lead)
    const sectionWords = (msg.sections ?? []).map((s) => wordChunks(s.text))
    const hasEvidence = Boolean(msg.evidence?.length)
    const hasConfidence = typeof msg.confidence === 'number'
    const hasNotice = Boolean(notice)
    const hasFooter = Boolean(msg.refs?.length || msg.followUps?.length)
    const total =
      (msg.memory ? 1 : 0) + textWords.length + sectionWords.reduce((n, w) => n + w.length, 0)
      + (hasEvidence ? 1 : 0) + (hasConfidence ? 1 : 0) + (hasNotice ? 1 : 0) + (hasFooter ? 1 : 0)
    return { textWords, sectionWords, hasEvidence, hasConfidence, hasNotice, hasFooter, total }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [msg.id])

  // A message that was already in the conversation before this component
  // ever mounted (seeded/persisted history, or a conversation switched back
  // into) renders complete and stays that way — only a message freshly
  // appended this session starts at 0 and types itself in. Reduce Motion
  // skips the reveal outright, same as every other animation in the app.
  const [revealed, setRevealed] = useState<number>(() => (
    prefs.reduceMotion || !peekFreshMessage(msg.id) ? plan.total : 0
  ))
  useEffect(() => { consumeFreshMessage(msg.id) }, [msg.id, consumeFreshMessage])

  useEffect(() => {
    if (prefs.reduceMotion) return
    // A few words per tick reads as natural typing without being slow —
    // character-by-character was explicitly ruled out. Self-clearing once
    // the plan is fully revealed, rather than depending on `revealed` and
    // re-subscribing every tick.
    const t = window.setInterval(() => {
      setRevealed((r) => {
        if (r >= plan.total) { window.clearInterval(t); return r }
        return Math.min(plan.total, r + 2)
      })
    }, 55)
    return () => window.clearInterval(t)
  }, [plan.total, prefs.reduceMotion])

  const done = revealed >= plan.total
  // Walks the plan from the start; each piece is shown in proportion to how
  // far `revealed` has got past the point where that piece begins.
  let cursor = 0
  const takeBlock = () => { cursor += 1; return done || revealed >= cursor }
  const takeWords = (chunks: string[]) => {
    const start = cursor
    cursor += chunks.length
    const n = Math.max(0, Math.min(chunks.length, revealed - start))
    return { text: chunks.slice(0, n).join(''), active: !done && n > 0 && n < chunks.length }
  }

  const memoryShown = msg.memory ? takeBlock() : false
  const firstNoticeShown = noticeFirst && plan.hasNotice ? takeBlock() : false
  const textReveal = takeWords(plan.textWords)
  const sectionReveals = plan.sectionWords.map((chunks) => takeWords(chunks))
  const evidenceShown = plan.hasEvidence ? takeBlock() : false
  // Safety before the small confidence status line, which closes the answer.
  const noticeShown = !noticeFirst && plan.hasNotice ? takeBlock() : false
  const confidenceShown = plan.hasConfidence ? takeBlock() : false
  const footerShown = plan.hasFooter ? takeBlock() : false

  return (
    <article className="answer vf-enter">
      <div className="answer-head">
        <AiMark />
        <div className="id">
          <b>Orion</b>
          {!isChat && <Cap>{msg.head ?? 'Answer'}</Cap>}
        </div>
        <span style={{ flex: 1 }} />
        {msg.mode === 'live' && <Chip icon="cam" size="sm">From Live</Chip>}
      </div>

      {msg.memory && memoryShown && (
        <div className="memory">
          <Icon name="history" size={15} stroke="var(--vf-muted)" width={1.8} />
          <span>{msg.memory}</span>
        </div>
      )}

      {notice && nm && noticeFirst && firstNoticeShown && (
        <div className={`notice ${notice.level}`} style={{ marginBottom: 10 }}>
          <Icon name={nm.icon} size={19} stroke={nm.colour} width={1.8} />
          <div>
            <Cap style={{ color: nm.colour }}>{nm.kind}</Cap>
            <div className="title">{notice.title}</div>
            {notice.text && <div className="text">{notice.text}</div>}
          </div>
        </div>
      )}

      {/* Plain prose. The type has always allowed `text`; before this it was
          only ever rendered for the user's own turn, so a conversational reply
          from the assistant came out as an empty card. */}
      {(msg.text || msg.lead) && (textReveal.text || done) && (
        <Prose text={textReveal.text} chat={isChat} cursor={textReveal.active ? REVEAL_CURSOR : undefined} />
      )}

      {(msg.kind === 'fallback' || msg.kind === 'offline') && done && (
        <Cap style={{ display: 'block', marginTop: 8, textTransform: 'none', letterSpacing: '0.02em', lineHeight: 1.5 }}>
          {msg.kind === 'fallback'
            ? 'No reasoning model is running, so Orion can’t interpret messages yet.'
            : 'The Orion engine is offline.'}
        </Cap>
      )}

      <div className="sections vf-stagger">
        {groupSections(msg.sections).map((g) => {
          const m = SECTION_META[g.kind]
          const numbered = m.numbered && !g.safety
          const shown = g.idx.filter((i) => sectionReveals[i]?.text)
          if (!shown.length) return null
          const item = (i: number) => {
            const r = sectionReveals[i]
            return <Markdown text={r.text} cursor={r.active ? REVEAL_CURSOR : undefined} />
          }
          const List = numbered ? 'ol' : 'ul'
          return (
            <section className={`rsec rsec-${g.kind}${g.safety ? ' rsec-safety' : ''}`} key={g.key}>
              <h4 className="rsec-h">
                {g.safety && <Icon name="shield" size={14} stroke="var(--vf-warn)" width={1.8} />}
                {g.label}
              </h4>
              {g.idx.length === 1
                ? <div className="rsec-one">{item(shown[0])}</div>
                : <List className="rsec-list">{shown.map((i) => <li key={i}>{item(i)}</li>)}</List>}
            </section>
          )
        })}

        {msg.evidence && msg.evidence.length > 0 && evidenceShown && (
          <div className="evidence vf-stagger">
            {msg.evidence.map((e) => (
              <figure key={e.id}>
                {e.url
                  ? <img className="shot" src={e.url} alt={e.caption} />
                  : <span className="shot" style={{ display: 'grid', placeItems: 'center' }}>
                      <Icon name="cam" size={20} stroke="var(--vf-muted)" />
                    </span>}
                <figcaption>{e.caption}</figcaption>
              </figure>
            ))}
          </div>
        )}

        {notice && nm && noticeShown && (
          <div className={`notice ${notice.level}`}>
            <Icon name={nm.icon} size={19} stroke={nm.colour} width={1.8} />
            <div>
              <Cap style={{ color: nm.colour }}>{nm.kind}</Cap>
              <div className="title">{notice.title}</div>
              {notice.text && <div className="text">{notice.text}</div>}
            </div>
          </div>
        )}
        {typeof msg.confidence === 'number' && confidenceShown && (
          <div className="confidence" aria-label={`${msg.confidenceLabel ?? 'Confidence'}: ${msg.confidence}%`}>
            <span className="meter" aria-hidden="true"><i style={{ width: `${msg.confidence}%` }} /></span>
            <span className="mono">{msg.confidence}%</span>
            <span>{msg.confidenceLabel ?? 'Confidence'}</span>
          </div>
        )}

      </div>

      {((msg.refs && msg.refs.length > 0) || (msg.followUps && msg.followUps.length > 0)) && footerShown && (
        <div className="answer-foot">
          {msg.refs?.map((r, i) => (
            <button key={i} type="button" className="btn ghost sm" onClick={() => onOpenDoc?.(r.doc, r.page)}>
              <Icon name="book" size={15} stroke="var(--vf-text-2)" />
              {r.doc} · p.{r.page}
            </button>
          ))}
          {msg.followUps?.map((f, i) => (
            <button key={i} type="button" className="btn sm" onClick={() => onFollowUp?.(f)}>{f}</button>
          ))}
        </div>
      )}
    </article>
  )
}

export function WorkTrail({ steps, index }: { steps: Step[]; index: number }) {
  // Until the backend reports a real tool step, nothing technical is known to
  // be happening — so it's a quiet typing indicator, not a work trail. Only a
  // technical turn ever streams steps.
  const realSteps = steps.filter((s) => s.label !== 'Thinking')
  if (!realSteps.length) {
    return (
      <div className="activity vf-enter" role="status" aria-label="Orion is replying">
        <AiMark size={26} />
        <span className="dots" aria-hidden="true"><i /><i /><i /></span>
      </div>
    )
  }
  steps = realSteps
  index = Math.min(index, steps.length)
  return (
    <article className="answer vf-enter">
      <div className="answer-head">
        <AiMark />
        <div className="id">
          <b>Orion is working</b>
          <Cap>{Math.min(index + 1, steps.length)} of {steps.length}</Cap>
        </div>
      </div>
      <div className="trail">
        {steps.map((s, i) => {
          const state = i < index ? 'done' : i === index ? 'run' : 'wait'
          return (
            <div className={`step ${state}`} key={i}>
              <span style={{ width: 18, display: 'grid', placeItems: 'center', flex: 'none' }}>
                {state === 'done' && <Icon name="check" size={13} stroke="var(--vf-ok)" width={2.2} />}
                {state === 'run' && <Spinner size={14} colour="var(--vf-text)" />}
                {state === 'wait' && <i style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--vf-border-strong)' }} />}
              </span>
              <Icon name={s.icon} size={15} stroke={state === 'wait' ? 'var(--vf-muted)' : 'var(--vf-text-2)'} />
              <span>{s.label}{state === 'run' ? '…' : ''}</span>
            </div>
          )
        })}
      </div>
    </article>
  )
}
