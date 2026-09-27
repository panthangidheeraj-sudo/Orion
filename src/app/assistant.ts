import type { Message, Step, VFile } from './types'
import { uid } from './util'
import { chatReply, classify, type ChatContext } from './conversation'
import { analyze, composeDiagnosis, hazardGate, matchHazard, pickClarifyingQuestion } from './diagnostics'

/**
 * STUB REASONING LAYER.
 *
 * Everything below stands in for the on-device vision-language model. It is
 * deliberately isolated behind two functions so the hackathon build can swap in
 * the real runtime without touching a single component:
 *
 *   planSteps(prompt, ctx)  -> the visible work trail (what the UI shows while thinking)
 *   answer(prompt, ctx)     -> the structured technician response
 *
 * Replace the bodies, keep the signatures.
 *
 * The diagnostic reasoning itself — which follow-up question to ask, and when
 * there's enough to actually diagnose something — lives in ./diagnostics.ts as
 * a symptom/slot decision table, not as hand-written strings in this file. See
 * that file's header for why.
 */

export interface AskContext {
  files: VFile[]
  hasHistory: boolean
  machine?: string
  webSearch: boolean
  mode: 'normal' | 'live'
  profession?: string
  /** Nobody attaches a photo to say hello, so an attachment settles it. */
  hasAttachments?: boolean
  /** Earlier user turns in this thread, oldest first — lets the diagnostic
   * engine carry facts forward instead of re-asking for them. */
  priorUserTexts?: string[]
}

const has = (s: string, ...words: string[]) => words.some((w) => s.includes(w))

/** The chat context the conversational layer needs, from the ask context. */
function chatContext(ctx: AskContext): ChatContext {
  return {
    documentCount: ctx.files.filter((f) => f.state === 'ready').length,
    machine: ctx.machine,
    hasHistory: ctx.hasHistory,
    mode: ctx.mode,
  }
}

/** The text this turn's diagnosis should be evaluated against: everything the
 * technician has said in this thread, plus the current message. */
function threadText(prompt: string, ctx: AskContext): string {
  return [...(ctx.priorUserTexts || []), prompt].join('\n')
}

export function planSteps(prompt: string, ctx: AskContext): Step[] {
  // Saying hello is not work. No trail, no fake latency.
  if (!ctx.hasAttachments && classify(prompt)) return []

  const p = prompt.toLowerCase()
  const steps: Step[] = []
  if (ctx.hasHistory) steps.push({ icon: 'history', label: 'Recalling what you’ve told me about this job', ms: 500 })

  if (ctx.mode === 'live') steps.push({ icon: 'cam', label: 'Analysing the live camera feed', ms: 800 })
  else if (ctx.hasAttachments || has(p, 'photo', 'image', 'picture', 'look')) {
    steps.push({ icon: 'eye', label: 'Analysing the attached image', ms: 800 })
  }

  const ready = ctx.files.filter((f) => f.state === 'ready')
  if (ready.length && !has(p, 'torque', 'nm', 'spec', 'tighten', 'bolt', 'nameplate', 'plate', 'rating', 'serial')) {
    steps.push({ icon: 'folder', label: `Checking your ${ready.length} indexed document${ready.length > 1 ? 's' : ''} for anything relevant`, ms: 700 })
  }

  const hazard = !ctx.hasAttachments ? matchHazard(prompt) : null
  if (hazard) {
    steps.push({ icon: 'warn', label: 'Checking for an immediate safety issue', ms: 400 })
  } else if (!ctx.hasAttachments) {
    const { topics, needsClarifying } = analyze(threadText(prompt, ctx))
    if (topics.length === 1) {
      steps.push({
        icon: 'sparks',
        label: needsClarifying
          ? `Working out what to ask about ${topics[0].label}`
          : `Weighing the likely causes of ${topics[0].label}`,
        ms: 800,
      })
    } else if (topics.length > 1) {
      steps.push({ icon: 'sparks', label: `Weighing ${topics.map((t) => t.label).join(' and ')} together`, ms: 800 })
    }
  }

  if (has(p, 'compare', 'last', 'previous', 'worse')) steps.push({ icon: 'gauge', label: 'Comparing with the previous inspection', ms: 750 })
  if (has(p, 'recall', 'latest', 'online', 'web')) {
    steps.push({
      icon: ctx.webSearch ? 'wifi' : 'wifioff',
      label: ctx.webSearch ? 'Searching the web' : 'Web search is off — using local sources',
      ms: 650,
    })
  }
  if (!steps.length) steps.push({ icon: 'sparks', label: 'Thinking it through', ms: 900 })
  return steps
}

export function answer(prompt: string, ctx: AskContext): Message {
  // Ordinary conversation gets an ordinary reply — no sections, no confidence
  // meter, no "I need more information" on a greeting.
  const intent = ctx.hasAttachments ? null : classify(prompt)
  if (intent) return chatReply(intent, chatContext(ctx))

  const p = prompt.toLowerCase()
  const machine = ctx.machine || 'this machine'
  const ready = ctx.files.filter((f) => f.state === 'ready')
  const base = {
    id: uid('a'),
    role: 'assistant' as const,
    at: Date.now(),
    mode: ctx.mode,
  }

  // --- safety first: sparks, burning smell, smoke, exposed conductors, arcing.
  // This runs before anything else in the function, and before the diagnostic
  // engine below, because a live-conductor or burning report has to be
  // addressed before any ordinary diagnostic question — never queued behind
  // one. See ./diagnostics.ts for why this isn't just another canned block.
  if (!ctx.hasAttachments) {
    const hazard = matchHazard(prompt)
    if (hazard) {
      const allText = threadText(prompt, ctx)
      const gate = hazardGate(hazard, allText)
      if (gate) {
        return { ...base, text: gate.text, notice: gate.notice, followUps: gate.followUps }
      }
      // Enough is already known (energised state + location) — fall through
      // to the diagnostic engine below, which will match the electrical-fault
      // topic and compose a real diagnosis instead of asking again.
    }
  }

  // --- adaptive symptom diagnosis: ask 1-2 targeted questions when something
  // is still missing, or compose a real diagnosis once enough is known.
  if (!ctx.hasAttachments) {
    const allText = threadText(prompt, ctx)
    const { topics, missingByTopic } = analyze(allText)
    if (topics.length) {
      const clarifying = pickClarifyingQuestion(missingByTopic, allText)
      if (clarifying) {
        return { ...base, text: clarifying.text }
      }
      const diagnosis = composeDiagnosis(topics, allText, machine)
      return {
        ...base,
        head: `Analysed ${ctx.mode === 'live' ? 'the live view' : 'your input'} · ${ready.length ? 'manual matched' : 'no manual indexed'}`,
        sections: diagnosis.sections,
        refs: ready.length ? [{ doc: ready[0].name.replace(/\.pdf$/i, ''), page: 42, quote: 'bearing limits' }] : [],
        confidence: diagnosis.confidence,
        confidenceLabel: diagnosis.confidenceLabel,
        memory: ctx.hasHistory ? `Based on your previous inspection of ${machine}` : undefined,
        notice: diagnosis.safetyHint
          ? { level: 'safety', title: diagnosis.safetyHint, text: 'Follow safe isolation practice before touching the machine.' }
          : undefined,
        followUps: ['Take the reading now', 'Open the report'],
      }
    }
  }

  // --- torque / specification lookup
  if (has(p, 'torque', 'nm', 'spec', 'tighten', 'bolt')) {
    if (!ready.length) {
      return {
        ...base,
        head: 'No indexed manual',
        notice: {
          level: 'need',
          title: 'I need the manual before I can give you a torque figure.',
          text: 'Attach the maintenance PDF for this machine and I will quote the value with its page number rather than guessing.',
        },
        followUps: ['Attach a manual'],
      }
    }
    return {
      ...base,
      head: `Read 1 document · page 42`,
      sections: [
        {
          kind: 'ref',
          text: 'The maintenance manual gives 48 Nm ± 4 Nm for M10 end-bell bolts on frame 132, tightened in a diagonal pattern.',
        },
        { kind: 'next', text: 'Retorque cold, then recheck after the first hour at load.' },
      ],
      refs: [{ doc: ready[0].name.replace(/\.pdf$/i, ''), page: 42, quote: 'table 6-3' }],
    }
  }

  // --- nameplate / OCR
  if (has(p, 'nameplate', 'plate', 'rating', 'model', 'serial', 'read')) {
    return {
      ...base,
      head: 'Read the nameplate · on-device OCR',
      sections: [
        { kind: 'observed', text: 'Nameplate reads 1LE1 · 11 kW · 1460 rpm · frame 132M, and the bearing code on the end bell is 6308-2Z/C3.' },
        { kind: 'next', text: 'Tell me the symptom and I will check it against the ratings I just read.' },
      ],
      evidence: [{ id: uid('e'), caption: 'Nameplate · 11 kW · 1460 rpm' }],
    }
  }

  // --- recalls / anything that genuinely needs the web
  if (has(p, 'recall', 'news', 'latest', 'online', 'price', 'buy')) {
    if (ctx.webSearch) {
      return {
        ...base,
        head: 'Web search is on',
        notice: {
          level: 'need',
          title: 'Web search is enabled but not wired up in this build.',
          text: 'The UI is ready for it: the query, its results and their sources would appear here as an evidence block alongside your manuals.',
        },
      }
    }
    return {
      ...base,
      head: 'Answered from local sources only',
      sections: [
        { kind: 'observed', text: 'I can confirm from your own documents what this part is specified as, and what your previous inspections recorded.' },
      ],
      notice: {
        level: 'need',
        title: 'That check needs the web, and web search is turned off.',
        text: 'I can answer from the manuals and your job history now, or you can turn web search on in Profile & Settings and ask again.',
      },
      followUps: ['Answer from manuals only'],
    }
  }

  // --- report
  if (has(p, 'report', 'write up', 'document this', 'sign off')) {
    return {
      ...base,
      head: 'Drafted from this conversation',
      sections: [
        { kind: 'observed', text: 'I have pulled the observations, readings and document references from this conversation into a draft inspection report.' },
        { kind: 'next', text: 'Open it from Reports, check the findings, then sign and export.' },
      ],
      followUps: ['Open the report'],
    }
  }

  // --- fallback: ask for what is missing rather than inventing. Reached only
  // when nothing above — safety, a matched symptom, a spec/nameplate/recall/
  // report request — applied, so there is genuinely nothing yet to go on.
  if (ctx.hasAttachments) {
    return {
      ...base,
      head: 'From what you have given me',
      notice: {
        level: 'need',
        title: "I can't read the image without the local backend running.",
        text: 'Vision analysis happens there, not in this offline demo responder. Start the backend '
          + '(see Profile & Settings → System status) and ask again, or tell me what you can see and '
          + "I'll work from that.",
      },
    }
  }
  return {
    ...base,
    head: ctx.mode === 'live' ? 'From the live view' : 'From what you have given me',
    notice: {
      level: 'need',
      title: 'I need a bit more before I can narrow this down.',
      text: 'Tell me the machine and the symptom — what changed, when it started, and what it sounds, smells or feels like. A photo or the camera will get me there faster.',
    },
    followUps: ['Open Live Mode', 'Attach a photo'],
  }
}
