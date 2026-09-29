import type { ReactNode } from 'react'

/**
 * A small, safe Markdown renderer for assistant answers.
 *
 * It changes presentation only: the model's text is never rewritten, and
 * nothing is injected as HTML — every piece is a React element. It understands
 * exactly what these answers use: **bold**, *italic*, `code`, "- / * / •"
 * bullets, "1." numbered lists, "#" headings, and a line that is only bold
 * (`**Mechanical looseness**`) which reads as a section heading.
 *
 * Streaming: the answer types itself in, so the text may end mid-marker
 * ("**Mech"). An unmatched opener is closed for the moment instead of being
 * shown as literal asterisks.
 */

type Block =
  | { kind: 'p'; text: string; spaced: boolean }
  | { kind: 'h'; text: string }
  | { kind: 'ul' | 'ol'; start?: number; items: { text: string; level: number }[] }

const BULLET = /^(\s*)([-*•])\s+(.*)$/
const NUMBER = /^(\s*)(\d{1,3})[.)]\s+(.*)$/
const HEADING = /^\s{0,3}#{1,4}\s+(.*?)\s*#*\s*$/
const BOLD_ONLY = /^\s*\*\*([^*]{1,90}?)\*\*\s*:?\s*$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let blank = false
  for (const raw of text.split('\n')) {
    const line = raw.replace(/\s+$/, '')
    if (line.trim() === '') { blank = blocks.length > 0; continue }
    if (RULE.test(line)) { blank = true; continue }

    const h = HEADING.exec(line) ?? BOLD_ONLY.exec(line)
    if (h) { blocks.push({ kind: 'h', text: h[1] }); blank = false; continue }

    const ul = BULLET.exec(line)
    const ol = ul ? null : NUMBER.exec(line)
    if (ul || ol) {
      const kind = ul ? 'ul' : 'ol'
      const m = (ul ?? ol)!
      const item = { text: m[3], level: m[1].length >= 2 ? 1 : 0 }
      const last = blocks[blocks.length - 1]
      // A blank line between two items of the same list keeps them one list.
      if (last && last.kind === kind) last.items.push(item)
      else blocks.push({ kind, start: ol ? Number(ol[2]) : undefined, items: [item] })
      blank = false
      continue
    }

    const last = blocks[blocks.length - 1]
    // An indented line straight after a list item continues that item.
    if (last && (last.kind === 'ul' || last.kind === 'ol') && !blank && /^\s{2,}\S/.test(line)) {
      last.items[last.items.length - 1].text += ' ' + line.trim()
      continue
    }
    blocks.push({ kind: 'p', text: line.trim(), spaced: blank })
    blank = false
  }
  return blocks
}

/** Close a marker the text ended in the middle of, so no raw `**` or backtick is ever shown. */
function closeOpen(s: string): string {
  let out = s
  if ((out.match(/\*\*/g) ?? []).length % 2 === 1) out += '**'
  if ((out.match(/`/g) ?? []).length % 2 === 1) out += '`'
  return out
}

const ITALIC = /(^|[\s(])\*([^\s*](?:[^*]*[^\s*])?)\*(?=$|[\s).,;:!?])/g

function italics(s: string, key: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  ITALIC.lastIndex = 0
  while ((m = ITALIC.exec(s))) {
    if (m.index + m[1].length > last) out.push(s.slice(last, m.index + m[1].length))
    out.push(<em key={`${key}i${m.index}`}>{m[2]}</em>)
    last = m.index + m[0].length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

function inline(src: string): ReactNode[] {
  const s = closeOpen(src)
  const out: ReactNode[] = []
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(...italics(s.slice(last, m.index), `t${last}`))
    if (m[1] !== undefined) out.push(<strong key={`b${m.index}`}>{italics(m[1], `b${m.index}`)}</strong>)
    else out.push(<code key={`c${m.index}`}>{m[2]}</code>)
    last = m.index + m[0].length
  }
  if (last < s.length) out.push(...italics(s.slice(last), `t${last}`))
  // A stray marker that could not be paired is never shown.
  return out.map((n) => (typeof n === 'string' ? n.replace(/\*\*/g, '') : n))
}

export function Markdown({ text, cursor }: { text: string; cursor?: ReactNode }) {
  const blocks = parseBlocks(text)
  return (
    <div className="md">
      {blocks.map((b, i) => {
        const tail = cursor && i === blocks.length - 1 ? cursor : null
        if (b.kind === 'h') {
          return <div key={i} className="md-h" role="heading" aria-level={4}>{inline(b.text)}{tail}</div>
        }
        if (b.kind === 'p') {
          return <p key={i} className={b.spaced ? 'spaced' : undefined}>{inline(b.text)}{tail}</p>
        }
        const List = b.kind
        return (
          <List key={i} start={b.kind === 'ol' && b.start && b.start !== 1 ? b.start : undefined}>
            {b.items.map((it, j) => (
              <li key={j} className={it.level ? 'sub' : undefined}>
                {inline(it.text)}{tail && j === b.items.length - 1 ? tail : null}
              </li>
            ))}
          </List>
        )
      })}
    </div>
  )
}

export default Markdown
