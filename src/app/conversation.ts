/**
 * Ordinary conversation.
 *
 * A field assistant that answers "hi" with "I need a bit more before I can
 * narrow this down" is behaving like a form, not a technician. A message that
 * is purely conversational gets a short, plain reply — no work trail, no
 * sections, no confidence meter, no hazard banner.
 *
 * This mirrors `backend/app/agent/conversation.py`, deliberately: the demo
 * should behave the same whether or not the local service is running, so the
 * two implementations are kept in step. The backend is the authority; this is
 * the offline twin.
 *
 * The classifier is conservative. It only fires when the *whole* message is
 * conversational, so "hi, the motor is overheating" goes to the diagnostic
 * path exactly as it should.
 */

import type { Message, Mode } from './types'
import { uid } from './util'

const GREETING = /^(hi|hey+|hello|yo|hiya|howdy|good\s+(morning|afternoon|evening|day)|morning|evening)\b/i
const THANKS = /^(thanks|thank\s+you|thankyou|ta|cheers|much\s+appreciated|appreciate\s+it|nice\s+one|perfect|great|awesome|brilliant|lovely)\b/i
const FAREWELL = /^(bye|goodbye|see\s+(you|ya)|later|good\s*night|gn|cya|that'?s\s+all|i'?m\s+done|all\s+done)\b/i
const ACK = /^(ok(ay)?|k|sure|right|alright|got\s+it|understood|yes|yeah|yep|yup|no|nope|fine|cool|noted|will\s+do|makes\s+sense)\b/i
const CAPABILITY = /(what\s+(can|do)\s+you\s+do|what\s+are\s+you\s+(for|able)|who\s+are\s+you|what\s+is\s+this|what'?s\s+this|how\s+(do|does)\s+(you|this)\s+work|what\s+can\s+i\s+ask|how\s+can\s+you\s+help|can\s+you\s+help|help\s+me\s+out|^help\b|^\?+$|what\s+are\s+your\s+(features|capabilities))/i
const SMALLTALK = /^(how\s+are\s+(you|things)|how'?s\s+it\s+going|what'?s\s+up|sup|you\s+(there|alive|awake|working))\b/i
const IDENTITY = /(what\s+model\s+are\s+you|are\s+you\s+(chatgpt|gpt|claude|an?\s+ai|a\s+(bot|robot))|who\s+(made|built)\s+you|are\s+you\s+real\s+ai|do\s+you\s+run\s+(locally|offline)|are\s+you\s+online)/i

/** If any of this is present the message is work, whatever else it contains. */
const TECHNICAL = /\b(motor|pump|drive|bearing|panel|fault|error|code|alarm|trip|leak|noise|vibrat\w*|overheat\w*|hot|smell|smoke|spark|volt\w*|amp\w*|current|pressure|temperature|torque|seal|gearbox|contactor|relay|fuse|breaker|terminal|winding|schematic|manual|diagram|inspect\w*|repair|replace|measure\w*|test|machine|equipment|broken|failing|stuck|jam\w*|rattle|grind\w*|squeal\w*|nameplate|rating\s*plate|serial|part\s*number|label|gauge|shaft|coupling|belt|valve|hose|filter|sensor|cable|wire|fan|impeller|spindle|reading|photo|picture|image|camera|this\s+(one|thing|unit|part))\b/i
/** A number with a unit is a measurement, not chat. */
const MEASUREMENT = /\d\s*(°|deg|c\b|f\b|v\b|a\b|ma\b|hz|rpm|bar|psi|nm|mm|kw|db)/i

const MAX_WORDS = 14

export type ChatIntent =
  | 'greeting' | 'smalltalk' | 'capability' | 'identity'
  | 'thanks' | 'farewell' | 'acknowledgement'

export interface ChatContext {
  documentCount: number
  machine?: string
  hasHistory: boolean
  mode: Mode
  /** What the engine actually is, so "are you ChatGPT" gets a true answer. */
  engine?: { modelId: string; provider: string; synthetic: boolean; online: boolean }
}

/** Returns an intent, or null when this is work and belongs in the agent loop. */
export function classify(text: string): ChatIntent | null {
  const raw = (text || '').trim()
  if (!raw) return null

  // Anything naming equipment, a symptom or a reading is work, even if it
  // opens with a greeting: "hi, the motor is overheating".
  if (TECHNICAL.test(raw) || MEASUREMENT.test(raw)) return null

  const stripped = raw.replace(/^[\s.,!?-]+|[\s.,!?-]+$/g, '')
  const words = stripped.split(/\s+/).filter(Boolean)

  if (CAPABILITY.test(stripped)) return 'capability'
  if (IDENTITY.test(stripped)) return 'identity'
  if (words.length > MAX_WORDS) return null
  if (SMALLTALK.test(stripped)) return 'smalltalk'
  if (GREETING.test(stripped)) return 'greeting'
  if (THANKS.test(stripped)) return 'thanks'
  if (FAREWELL.test(stripped)) return 'farewell'
  if (ACK.test(stripped) && words.length <= 4) return 'acknowledgement'
  return null
}

/**
 * A conversational turn: plain text, none of the diagnostic furniture.
 *
 * That includes suggestion chips. The reply already says what to do next, and a
 * row of buttons under "hello" is the product showing off rather than a
 * technician answering. Follow-ups stay where they earn their place: under a
 * diagnosis, where they point at a specific page or a specific next test.
 */
export function chatReply(intent: ChatIntent, ctx: ChatContext): Message {
  const docs = ctx.documentCount
  const base = { id: uid('a'), role: 'assistant' as const, at: Date.now(), mode: ctx.mode }
  const plain = (text: string): Message => ({ ...base, text })

  switch (intent) {
    case 'greeting':
      if (ctx.machine) {
        return plain(
          `Hello. You've got ${ctx.machine} open — tell me what's changed, or point the camera at it.`)
      }
      if (ctx.hasHistory) return plain('Hello again. What are you looking at?')
      return plain(
        'Hello. Tell me what the machine is doing — the symptom, when it started, what it '
        + 'sounds or smells like. A photo or the camera gets me there faster.')

    case 'smalltalk':
      return plain('Running fine and entirely on this machine. What are we looking at?')

    case 'capability':
      return plain(
        [
          "I'm a field assistant for inspecting and repairing equipment. Practically:",
          '',
          "• Describe a symptom and I'll work through likely causes and what to test next.",
          '• Show me a photo, or open Live Mode and point the camera at the machine.',
          "• Upload manuals, datasheets and schematics — I'll search them and cite the page.",
          '• I keep a record per machine, so next visit I can tell you what we found last time.',
          "• I'll write the service report from what was actually recorded.",
          '',
          "Two things I won't do: invent a measurement, or tell you to work on live equipment. "
          + "If I don't know, I'll say so and ask for the reading I need.",
          ...(docs ? [] : ['', 'Nothing is in the vault yet — drop a manual in and I can start citing it.']),
        ].join('\n'))

    case 'identity': {
      const e = ctx.engine
      const where = 'running on this machine — nothing you show me leaves it unless you turn web research on'
      if (!e || !e.online) {
        return plain(
          `I'm VisionField Copilot, ${where}. The local service isn't running right now, so `
          + "you're seeing the built-in demo responses rather than the real engine.")
      }
      const detail = e.synthetic
        ? `Right now the reasoning is a deterministic stand-in (${e.modelId}), not a language `
          + 'model, because no model has been exported to this machine yet. It still reads your '
          + "manuals and your job history; it just can't hold an open-ended conversation."
        : `Reasoning is running on ${e.modelId}.`
      return plain(`I'm VisionField Copilot, ${where}. ${detail}`)
    }

    case 'thanks':
      return plain('Any time. Anything else on this machine?')

    case 'farewell':
      return plain(
        ctx.machine
          ? `Right you are. ${ctx.machine} stays open — everything recorded is saved on this machine for next time.`
          : "Right you are. Everything's saved locally for next time.",
      )

    case 'acknowledgement':
    default:
      return plain("Go on — what's it doing?")
  }
}
