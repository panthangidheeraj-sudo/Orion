import { AiMark, Icon } from './Icon'
import { Chip, Cap, Spinner } from './bits'
import type { Message, Section, Step, VFile } from '../app/types'
import { fmtClock } from '../app/util'
import { FileChip } from './Composer'

const SECTION_META: Record<Section['kind'], { label: string; icon: string; colour: string }> = {
  observed: { label: 'Observed', icon: 'eye', colour: 'var(--vf-ok)' },
  inferred: { label: 'Inferred', icon: 'sparks', colour: 'var(--vf-text)' },
  next: { label: 'Next check', icon: 'check', colour: 'var(--vf-text-2)' },
  measure: { label: 'Measurements', icon: 'ruler', colour: 'var(--vf-text-2)' },
  ref: { label: 'Document reference', icon: 'book', colour: 'var(--vf-text-2)' },
}

const NOTICE_META = {
  safety: { kind: 'Safety', icon: 'shield', colour: 'var(--vf-warn)' },
  need: { kind: 'More information needed', icon: 'info', colour: 'var(--vf-text)' },
  confirmed: { kind: 'Confirmed finding', icon: 'check', colour: 'var(--vf-ok)' },
  error: { kind: 'Could not complete', icon: 'warn', colour: 'var(--vf-danger)' },
} as const

export function UserMessage({ msg, files }: { msg: Message; files: VFile[] }) {
  const attached = files.filter((f) => msg.attachments?.includes(f.id))
  return (
    <div className="msg-user">
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
function Prose({ text, chat }: { text: string; chat: boolean }) {
  const lines = text.split('\n')
  const paragraphs: { text: string; spaced: boolean }[] = []
  let blankBefore = false
  for (const line of lines) {
    if (line.trim() === '') { blankBefore = paragraphs.length > 0; continue }
    paragraphs.push({ text: line, spaced: blankBefore })
    blankBefore = false
  }
  return (
    <div className={`prose${chat ? ' prose-chat' : ''}`}>
      {paragraphs.map((p, i) => (
        <p key={i} className={p.spaced ? 'spaced' : undefined}>{p.text}</p>
      ))}
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
  const notice = msg.notice
  const nm = notice ? NOTICE_META[notice.level] : null
  // An ordinary conversational turn: prose, and none of the diagnostic
  // furniture. Recognised by shape so it needs no extra field on the wire.
  const isChat = Boolean(msg.text) && !msg.sections?.length && !notice
    && !msg.refs?.length && !msg.evidence?.length
  return (
    <article className="answer">
      <div className="answer-head">
        <AiMark />
        <div className="id">
          <b>VisionField</b>
          {!isChat && <Cap>{msg.head ?? 'Answer'}</Cap>}
        </div>
        <span style={{ flex: 1 }} />
        {msg.mode === 'live' && <Chip icon="cam" size="sm">From Live</Chip>}
      </div>

      {msg.memory && (
        <div className="memory">
          <Icon name="history" size={15} stroke="var(--vf-muted)" width={1.8} />
          <span>{msg.memory}</span>
        </div>
      )}

      {/* Plain prose. The type has always allowed `text`; before this it was
          only ever rendered for the user's own turn, so a conversational reply
          from the assistant came out as an empty card. */}
      {msg.text && <Prose text={msg.text} chat={isChat} />}

      <div className="sections">
        {msg.sections?.map((s, i) => {
          const m = SECTION_META[s.kind]
          return (
            <section className={`section ${s.kind}`} key={i}>
              <span className="badge"><Icon name={m.icon} size={14} stroke={m.colour} width={1.8} /></span>
              <div className="body">
                <Cap style={{ marginBottom: 6 }}>{m.label}</Cap>
                <p>{s.text}</p>
              </div>
            </section>
          )
        })}

        {msg.evidence && msg.evidence.length > 0 && (
          <div className="evidence">
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

        {typeof msg.confidence === 'number' && (
          <div className="confidence">
            <Icon name="gauge" size={18} stroke="var(--vf-text-2)" width={1.8} />
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
                <b style={{ fontSize: 13 }}>{msg.confidenceLabel ?? 'Confidence'}</b>
                <span className="mono" style={{ fontSize: 11, color: 'var(--vf-muted)' }}>{msg.confidence}% confidence</span>
              </div>
              <div className="meter"><i style={{ width: `${msg.confidence}%` }} /></div>
            </div>
          </div>
        )}

        {notice && nm && (
          <div className={`notice ${notice.level}`}>
            <Icon name={nm.icon} size={19} stroke={nm.colour} width={1.8} />
            <div>
              <Cap style={{ color: nm.colour }}>{nm.kind}</Cap>
              <div className="title">{notice.title}</div>
              {notice.text && <div className="text">{notice.text}</div>}
            </div>
          </div>
        )}
      </div>

      {((msg.refs && msg.refs.length > 0) || (msg.followUps && msg.followUps.length > 0)) && (
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
  return (
    <article className="answer">
      <div className="answer-head">
        <AiMark />
        <div className="id">
          <b>VisionField is working</b>
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
