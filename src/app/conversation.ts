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
// "what is this?" on its own is a capability question; "what is this
// component?" names a thing and must fall through to the technical check
// below, so those two forms are anchored to the whole message.
const CAPABILITY = /(what\s+(can|do)\s+you\s+do|what\s+are\s+you\s+(for|able)|who\s+are\s+you|^what\s+is\s+this\??$|^what'?s\s+this\??$|how\s+(do|does)\s+(you|this)\s+work|what\s+can\s+i\s+ask|how\s+can\s+you\s+help|can\s+you\s+help|help\s+me\s+out|^help\b|^\?+$|what\s+are\s+your\s+(features|capabilities))/i
const SMALLTALK = /^(how\s+are\s+(you|things)|how'?s\s+it\s+going|what'?s\s+up|sup|you\s+(there|alive|awake|working))\b/i
const IDENTITY = /(what\s+model\s+are\s+you|are\s+you\s+(chatgpt|gpt|claude|an?\s+ai|a\s+(bot|robot))|who\s+(made|built)\s+you|are\s+you\s+real\s+ai|do\s+you\s+run\s+(locally|offline)|are\s+you\s+online|what'?s\s+your\s+name|what\s+is\s+your\s+name|do\s+you\s+have\s+a\s+name)/i
/** Playful, opinion-style questions — "do you like cats?", "what's your favourite tool?" */
const OPINION = /\b(do\s+you\s+(like|love|enjoy|prefer|hate)|what'?s\s+your\s+favou?rite|what\s+is\s+your\s+favou?rite|are\s+you\s+(a\s+fan\s+of|into))\b/i
/** Asking for a joke or something lighthearted. */
const JOKE = /\b(tell\s+me\s+a\s+joke|know\s+any\s+jokes?|got\s+any\s+jokes?|make\s+me\s+laugh|say\s+something\s+funny|be\s+funny)\b/i

// If any of this is present the message is work, whatever else it contains.
// Words that can take a plural/gerund/past-tense suffix ("smells", "sparking",
// "burnt") carry \w* so the stem still matches — a bare word with a trailing
// \b boundary does NOT match its own inflected forms, which used to let
// "it smells like burning and small sparks" slip through as plain chat.
const TECHNICAL = /\b(motor|pump|drive|bearing|panel|fault|error|code\w*|alarm|trip\w*|leak\w*|noise|nois\w*|vibrat\w*|overheat\w*|hot|smell\w*|smok\w*|spark\w*|burn\w*|scorch\w*|arc(?:ing|ed)?|volt\w*|amp\w*|current|pressure|temperature|torque|seal|gearbox|contactor|relay|fuse|breaker|terminal|winding|schematic|manual|diagram|inspect\w*|repair\w*|replace\w*|measure\w*|test\w*|machine|equipment|component\w*|broken|fail\w*|stuck|jam\w*|rattl\w*|grind\w*|squeal\w*|nameplate|rating\s*plate|serial|part\s*number|label|gauge|shaft|coupling|belt|valve|hose|filter|sensor|cable|wire|fan|impeller|spindle|reading|photo|picture|image|camera|this\s+(one|thing|unit|part))\b/i
/** A number with a unit is a measurement, not chat. */
const MEASUREMENT = /\d\s*(°|deg|c\b|f\b|v\b|a\b|ma\b|hz|rpm|bar|psi|nm|mm|kw|db)/i
/** A fault code or part number — "E17", "24VDC", "NSK6203" — names something
 * specific even though it isn't an English word the TECHNICAL list can name. */
const CODE_TOKEN = /\b(?=[a-z]*\d)(?=[a-z0-9-]*[a-z])[a-z][a-z0-9-]{1,9}\b/i

const MAX_WORDS = 14

export type ChatIntent =
  | 'greeting' | 'smalltalk' | 'capability' | 'identity'
  | 'thanks' | 'farewell' | 'acknowledgement' | 'opinion' | 'joke'

export interface ChatContext {
  documentCount: number
  machine?: string
  hasHistory: boolean
  mode: Mode
  /** What the engine actually is, so "are you ChatGPT" gets a true answer. */
  engine?: { modelId: string; provider: string; synthetic: boolean; online: boolean }
}

/**
 * Returns an intent, or null when this is work and belongs in the agent loop.
 *
 * The default matters as much as the patterns: a message with no technical
 * signal at all and short enough to plausibly be chat is treated as chat even
 * when it doesn't match one of the named categories below ("do you like
 * cats?", "tell me a joke"). The old version defaulted the other way — anything
 * that didn't match a known casual phrasing fell through to the diagnostic
 * path, which is why those questions used to come back as "more information
 * needed". Only a technical or measurement cue routes to work; everything
 * else short and plain is a conversation.
 */
export function classify(text: string): ChatIntent | null {
  const raw = (text || '').trim()
  if (!raw) return null

  // Anything naming equipment, a symptom, a reading, or a code/part number is
  // work, even if it opens with a greeting: "hi, the motor is overheating".
  if (TECHNICAL.test(raw) || MEASUREMENT.test(raw) || CODE_TOKEN.test(raw)) return null

  const stripped = raw.replace(/^[\s.,!?-]+|[\s.,!?-]+$/g, '')
  const words = stripped.split(/\s+/).filter(Boolean)

  if (CAPABILITY.test(stripped)) return 'capability'
  if (IDENTITY.test(stripped)) return 'identity'
  if (JOKE.test(stripped)) return 'joke'
  if (OPINION.test(stripped)) return 'opinion'
  if (words.length > MAX_WORDS) return null
  if (SMALLTALK.test(stripped)) return 'smalltalk'
  if (GREETING.test(stripped)) return 'greeting'
  if (THANKS.test(stripped)) return 'thanks'
  if (FAREWELL.test(stripped)) return 'farewell'
  if (ACK.test(stripped) && words.length <= 4) return 'acknowledgement'
  // Nothing named above matched. Staying conservative here matters: "the
  // flange on the pump is behaving oddly" has no technical keyword this file
  // happens to list, but it is still a technician describing a machine, not
  // small talk, and the diagnostic path already says "I don't recognise that
  // pattern" honestly rather than inventing one — a much safer failure mode
  // than routing a real complaint into a joke reply. The specific patterns
  // above (opinion/joke/identity/capability/smalltalk/…) are what actually
  // closed Bug 1's gap; this default is deliberately unchanged from before.
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
          `I'm Orion, ${where}. The local service isn't running right now, so `
          + "you're seeing the built-in demo responses rather than the real engine.")
      }
      const detail = e.synthetic
        ? `Right now the reasoning is a deterministic stand-in (${e.modelId}), not a language `
          + 'model, because no model has been exported to this machine yet. It still reads your '
          + "manuals and your job history; it just can't hold an open-ended conversation."
        : `Reasoning is running on ${e.modelId}.`
      return plain(`I'm Orion, ${where}. ${detail}`)
    }

    case 'thanks':
      return plain('Any time. Anything else on this machine?')

    case 'farewell':
      return plain(
        ctx.machine
          ? `Right you are. ${ctx.machine} stays open — everything recorded is saved on this machine for next time.`
          : "Right you are. Everything's saved locally for next time.",
      )

    case 'opinion':
      return plain("I don't really have preferences — I'm tuned for machines, not opinions. "
        + "Happy to chat, but I'm most useful once we're looking at some equipment. What have you got?")

    case 'joke': {
      const jokes = [
        "Why did the motor file a complaint? It said it was being taken for a spin.",
        "Why do bearings make terrible secret-keepers? They always end up squealing.",
        "A technician's favourite genre of music? Anything with a good torque sequence.",
      ]
      const pick = jokes[Date.now() % jokes.length]
      return plain(`${pick} ...Anyway — what are we working on?`)
    }

    case 'acknowledgement':
    default:
      return plain("Go on — what's it doing?")
  }
}
