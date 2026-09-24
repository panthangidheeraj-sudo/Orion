import type { Message, Section, Step, VFile, Detection, OcrTag } from './types'
import { uid } from './util'
import { chatReply, classify, type ChatContext } from './conversation'

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

export function planSteps(prompt: string, ctx: AskContext): Step[] {
  // Saying hello is not work. No trail, no fake latency.
  if (!ctx.hasAttachments && classify(prompt)) return []

  const p = prompt.toLowerCase()
  const steps: Step[] = []
  if (ctx.hasHistory) steps.push({ icon: 'history', label: 'Retrieving the previous inspection', ms: 600 })
  const ready = ctx.files.filter((f) => f.state === 'ready')
  if (ready.length) {
    steps.push({ icon: 'folder', label: `Searching your documents — ${ready.length} indexed`, ms: 700 })
    steps.push({ icon: 'book', label: 'Reading the manual', ms: 900 })
  }
  if (ctx.mode === 'live') steps.push({ icon: 'cam', label: 'Analysing the live camera', ms: 800 })
  else if (has(p, 'photo', 'image', 'picture', 'look')) steps.push({ icon: 'eye', label: 'Analysing image', ms: 800 })
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

  // --- vibration / bearing
  if (has(p, 'vibrat', 'bearing', 'rattle', 'noise', 'rumble', 'hot', 'temperature', 'heat')) {
    const sections: Section[] = [
      {
        kind: 'observed',
        text: `The drive-end bearing housing on ${machine} is running hotter than the fan end and the vibration is strongest along the shaft axis. The coupling faces look parallel.`,
      },
      {
        kind: 'inferred',
        text: 'Drive-end bearing degradation, most likely lubricant breakdown rather than misalignment.',
      },
      {
        kind: 'next',
        text: 'Take an axial vibration reading at the drive-end housing at full load. Above 7.1 mm/s RMS the bearing has reached replacement threshold under ISO 10816-3.',
      },
    ]
    return {
      ...base,
      head: `Analysed ${ctx.mode === 'live' ? 'the live view' : 'your input'} · ${ready.length ? 'manual matched' : 'no manual indexed'}`,
      sections,
      refs: ready.length ? [{ doc: ready[0].name.replace(/\.pdf$/i, ''), page: 42, quote: 'bearing limits' }] : [],
      confidence: 72,
      confidenceLabel: 'Likely cause — needs confirmation',
      memory: ctx.hasHistory ? `Based on your previous inspection of ${machine}` : undefined,
      notice: {
        level: 'safety',
        title: 'Lock out the drive before touching the housing.',
        text: 'Above 70 °C at the housing. Let it cool or use a non-contact probe for the reading.',
      },
      followUps: ['Take the reading now', 'What is the bearing part number?'],
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

  // --- fallback: ask for what is missing rather than inventing
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

/** Placeholder detections for Live Mode until the real detector is wired in. */
export const DEMO_DETECTIONS: Detection[] = [
  { id: 'd1', label: 'Motor frame', confidence: 0.96, x: 18, y: 34, w: 44, h: 30, tone: 'neutral' },
  { id: 'd2', label: 'Drive-end housing', confidence: 0.88, x: 58, y: 44, w: 16, h: 26, tone: 'warn' },
  { id: 'd3', label: 'Terminal box', confidence: 0.61, x: 33, y: 24, w: 14, h: 11, tone: 'neutral' },
]

export const DEMO_OCR: OcrTag[] = [
  { id: 'o1', x: 70, y: 22, label: 'Nameplate', value: '1LE1 · 11 kW · 1460 rpm' },
  { id: 'o2', x: 70, y: 66, label: 'Bearing code', value: '6308-2Z/C3' },
]

export const LIVE_PROMPTS = [
  'Hold the camera steady on the drive end and I will read the nameplate first.',
  'Nameplate read: 1LE1 · 11 kW · 1460 rpm · frame 132M.',
  'The drive-end housing is running hotter than the fan end. Put the probe on the housing at the three o’clock position.',
  'That reading puts it in zone C of ISO 10816-3. I would schedule the bearing for replacement.',
]
