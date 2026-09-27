/**
 * Adaptive diagnostic question-selection.
 *
 * This replaces a fixed catalogue of canned response blocks with a small
 * decision engine: each symptom is a set of *slots* — the specific pieces of
 * information a technician would actually need before they could narrow the
 * cause down — and the engine asks only for whichever of those are still
 * missing, at most two at a time, in whatever order matters most for that
 * symptom. It never asks for something already in the conversation, because
 * every slot is tested against the accumulated text of the thread, not just
 * the latest message.
 *
 * Adding a new symptom means adding a table row (cues, slots, causes,
 * tests) — not a new hand-written paragraph of dialogue. That is the whole
 * point: the questions come from evaluating what's missing, not from a
 * bigger and bigger pile of pre-written strings.
 *
 * Safety is handled first and separately (`matchHazard` / `hazardGate`),
 * ahead of and independent of the symptom table, because a live-conductor or
 * burning-smell report has to be addressed before anything else — never
 * queued behind an ordinary diagnostic question.
 */

import type { Section } from './types'

// ---------------------------------------------------------------- facts

/** A place on the machine. Reused across several symptoms' location slots. */
// "motor" and "pump" alone name the machine, not a location on it — that
// alternative requires "body"/"housing"/"casing" so a message that just
// mentions the machine's name doesn't get mistaken for having already
// pinned down where on it the symptom is.
const LOCATION_RE =
  /\b(drive[\s-]?end|non[\s-]?drive[\s-]?end|fan[\s-]?end|mounting(?:\s+base)?|base|terminal\s*box|terminal|cable|cord|junction\s*box|motor\s+(?:body|housing|casing)|winding|bearing\s*housing|housing|casing|seal|flange|gasket|hose|fitting|valve|pump\s+casing|coupling|panel)\b/i

const ONSET_RE = /\b(sudden(?:ly)?|all\s+at\s+once|out\s+of\s+nowhere|gradual(?:ly)?|over\s+time|been\s+(?:getting|building)\s+(?:worse|up)|got\s+worse\s+over)\b/i

const TIMING_RE = /\b(immediately|right\s+away|straight\s+away|instantly|after\s+(?:about\s+)?\d+\s*(?:sec(?:ond)?s?|min(?:ute)?s?|hours?|hrs?)|within\s+(?:a\s+)?(?:few\s+)?(?:seconds|minutes)|on\s+start-?up|at\s+start-?up|as\s+soon\s+as)\b/i

const LOAD_CORRELATION_RE = /\b(under\s+load|no\s+load|at\s+idle|full\s+load|light\s+load|heavy\s+load|when\s+(?:it'?s\s+)?loaded|at\s+start-?up|running\s+light|tracks?\s+(?:the\s+)?speed|with\s+speed|as\s+it\s+speeds\s+up)\b/i

const RESETS_RE = /\b(resets?\s+(?:itself|automatically|on\s+its\s+own)?|reset\s+it\s+manually|won'?t\s+reset|trips?\s+again|stays?\s+tripped|keeps?\s+tripping)\b/i

const PATTERN_RE = /\b(steady|constant|non-?stop|always|only\s+when\s+(?:it'?s\s+)?running|only\s+under\s+load|intermittent|comes?\s+and\s+goes)\b/i

const TEMP_READING_RE = /(-?\d+(?:\.\d+)?)\s*(°\s?[cf]\b|deg(?:rees)?\s?[cf]?)/i
const CURRENT_READING_RE = /(-?\d+(?:\.\d+)?)\s*(a\b|amps?\b|ma\b)/i
const VIBRATION_READING_RE = /(-?\d+(?:\.\d+)?)\s*(mm\/s\b)/i
const VOLTAGE_READING_RE = /(-?\d+(?:\.\d+)?)\s*(v\b|volts?\b|vac\b|vdc\b)/i
const PRESSURE_READING_RE = /(-?\d+(?:\.\d+)?)\s*(psi\b|bar\b)/i

const RATE_OF_RISE_RE = /\b(sudden(?:ly)?|gradual(?:ly)?|steadily|been\s+(?:climbing|rising|creeping\s+up)|over\s+the\s+(?:last|past)\s+\d+)\b/i

const NO_START_DETAIL_RE = /\b(hum(?:s|ming)?|click(?:s|ing)?|completely\s+(?:dead|silent)|no\s+sound|no\s+noise|lights?\s+(?:on|off|flashing)|indicator)\b/i
const NO_START_HISTORY_RE = /\b(worked\s+(?:fine|ok|okay)?\s*(?:yesterday|before|last\s+time|previously)|new\s+(?:issue|problem)|first\s+time|just\s+(?:started|began))\b/i

const ERROR_CODE_RE = /\b(?:code|error|fault|alarm)\s*[:#-]?\s*([a-z]{0,3}\d{1,4}[a-z]?)\b/i
const WHEN_APPEARED_RE = /\b(while\s+(?:running|starting|idle)|during\s+(?:start-?up|operation)|as\s+soon\s+as|right\s+after|when\s+(?:i|we)\s+(?:started|turned\s+on))\b/i

const PRESSURE_SYSTEM_RE = /\b(hydraulic|pneumatic|air\s+(?:line|system)|water\s+(?:line|system))\b/i
const SMELL_TYPE_RE = /\b(chemical|solvent|coolant|rubber|electrical|musty|sweet|acrid|sour|rotten)\b/i
const WHEN_NOTICED_RE = /\b(just\s+now|today|this\s+morning|yesterday|since\s+(?:it\s+)?started|when\s+(?:it|the\s+machine)\s+(?:starts?|runs?|warms?\s+up)|constantly|comes?\s+and\s+goes)\b/i

/** Whether the equipment's energised/isolated state has already been stated. */
const ENERGIZED_KNOWN_RE = /\b(still\s+(?:energi[sz]ed|live|running|powered|on|connected)|isolated|switched\s+off|turned\s+off|de-?energi[sz]ed|locked\s+out|shut\s+down|powered\s+down|not\s+(?:running|powered)|it'?s\s+off\b|it\s+is\s+off\b|powered\s+off)\b/i
const HAZARD_LOCATION_RE = /\b(terminal\s*box|terminal|cable|cord|wire|motor\s*(?:body|housing)?|drive\s*(?:unit|body)?|junction\s*box|panel)\b/i

function has(re: RegExp, text: string) {
  return re.test(text)
}

// ---------------------------------------------------------------- slots

interface Slot {
  id: string
  priority: number
  known: (text: string) => boolean
  /** A clause, not a full sentence — composeQuestion() joins and punctuates it. */
  ask: (text: string) => string
}

function locOf(text: string): string | null {
  const m = LOCATION_RE.exec(text)
  return m ? m[0].toLowerCase() : null
}

interface Topic {
  key: string
  label: string
  cues: RegExp
  ack: string
  slots: Slot[]
  causes: { label: string; text: string }[]
  tests: string[]
  /** [name, unit] readings worth confirming once a full diagnosis is composed. */
  measurements: [string, string, RegExp][]
  safetyHint?: string
}

const TOPICS: Topic[] = [
  {
    key: 'vibration',
    label: 'the vibration',
    cues: /\b(vibrat\w*|shak(?:e|ing)|wobbl\w*|unbalanc\w*)\b/i,
    ack: 'Vibration like that usually comes down to the bearings, alignment or a loose mount.',
    slots: [
      { id: 'location', priority: 10, known: (t) => has(LOCATION_RE, t),
        ask: () => 'where is it strongest — the drive end, the fan end, or the mounting/base' },
      { id: 'onset', priority: 9, known: (t) => has(ONSET_RE, t),
        ask: () => 'did it start suddenly or build up gradually' },
    ],
    causes: [
      { label: 'Likely', text: 'Bearing wear or damage' },
      { label: 'Likely', text: 'Shaft or coupling misalignment' },
      { label: 'Possible', text: 'Rotor or driven-load imbalance' },
      { label: 'Possible', text: 'Loose mounting feet or soft foot' },
    ],
    tests: [
      'Vibration amplitude at the drive-end and non-drive-end bearings',
      'Coupling alignment with a dial gauge or laser',
      'Mounting bolt torque and shim condition',
    ],
    measurements: [['vibration', 'mm/s', VIBRATION_READING_RE]],
  },
  {
    key: 'noise',
    label: 'the noise',
    cues: /\b(grind(?:ing)?|squeal(?:ing)?|rattl\w*|knock(?:ing)?|whin(?:e|ing)|screech\w*|noisy|noise|rumbl\w*|\bhum\b|humming)\b/i,
    ack: 'That kind of noise is almost always a bearing, or something rotating touching something it shouldn’t.',
    slots: [
      { id: 'loadCorrelation', priority: 10, known: (t) => has(LOAD_CORRELATION_RE, t),
        ask: () => 'does it track speed or load, or is it there even at idle' },
      { id: 'location', priority: 9, known: (t) => has(LOCATION_RE, t),
        ask: () => 'where is it coming from' },
    ],
    causes: [
      { label: 'Likely', text: 'Bearing degradation — grinding or rumbling under load' },
      { label: 'Possible', text: 'Contact between a rotating and a stationary part' },
      { label: 'Possible', text: 'A loose fastener or guard resonating' },
    ],
    tests: [
      'Listen at each bearing with the machine running, and note whether the pitch tracks shaft speed',
      'Coast-down test — does the noise follow the machine down as it slows',
      'Guard and fastener check with the machine isolated',
    ],
    measurements: [['vibration', 'mm/s', VIBRATION_READING_RE]],
  },
  {
    key: 'overheating',
    label: 'the heat',
    cues: /\b(overheat\w*|running\s+hot|too\s+hot|hot\s+to\s+(?:the\s+)?touch|temperature\w*\s+high|thermal|hot|temperature|heat)\b/i,
    ack: 'Running hot like that usually points at restricted cooling, overload, or a bearing adding friction.',
    slots: [
      { id: 'location', priority: 10, known: (t) => has(LOCATION_RE, t),
        ask: () => 'where is it hottest — the bearing housing, the winding end, or the whole casing' },
      { id: 'reading', priority: 9, known: (t) => has(TEMP_READING_RE, t),
        ask: (t) => { const loc = locOf(t); return `do you have a temperature reading${loc ? ` from the ${loc}` : ''}` } },
      { id: 'rateOfRise', priority: 6, known: (t) => has(RATE_OF_RISE_RE, t),
        ask: () => 'has it been climbing gradually, or did it jump quickly' },
    ],
    causes: [
      { label: 'Likely', text: 'Restricted cooling — blocked airflow, fouled fins or a failed fan' },
      { label: 'Likely', text: 'Sustained overload or duty beyond the nameplate rating' },
      { label: 'Possible', text: 'Bearing friction or misalignment adding mechanical load' },
      { label: 'Possible', text: 'Degraded winding insulation drawing excess current' },
    ],
    tests: [
      'Surface temperature at the housing and the bearing end, with the ambient noted',
      'Running current on each phase against the nameplate rating',
      'Airflow path and fan rotation with the machine isolated',
    ],
    measurements: [['temperature', '°C', TEMP_READING_RE], ['current', 'A', CURRENT_READING_RE]],
    safetyHint: 'Hot surfaces — let it cool or use a non-contact probe before touching it.',
  },
  {
    key: 'electrical_trip',
    label: 'the trip',
    cues: /\b(breaker|trip(?:s|ped|ping)?|fuse\b|overload|earth\s+fault|rcd\b|gfci)\b/i,
    ack: 'A repeat trip means the protection is doing its job — something is drawing too much current or there is a fault to earth.',
    slots: [
      { id: 'timing', priority: 10, known: (t) => has(TIMING_RE, t),
        ask: () => 'does it trip immediately on start-up, or only after it has been running for a while' },
      { id: 'loadCorrelation', priority: 9, known: (t) => has(LOAD_CORRELATION_RE, t),
        ask: () => 'is it under load when it trips, or does it happen even with nothing on it' },
      { id: 'resets', priority: 7, known: (t) => has(RESETS_RE, t),
        ask: () => 'does it reset and hold, or trip again straight away' },
    ],
    causes: [
      { label: 'Likely', text: 'Winding or cable insulation failure to earth' },
      { label: 'Likely', text: 'Mechanical load beyond rating causing sustained overcurrent' },
      { label: 'Possible', text: 'The protection device is set below actual duty, or is itself degraded' },
    ],
    tests: [
      'Insulation resistance winding-to-earth, machine isolated and proven dead',
      'Running current per phase against the nameplate',
      'Protection setting against the nameplate full-load current',
    ],
    measurements: [['current', 'A', CURRENT_READING_RE]],
    safetyHint: 'Isolate and prove dead before any winding or cable test.',
  },
  {
    key: 'leak',
    label: 'the leak',
    cues: /\b(leak(?:ing|s)?|drip(?:ping|s)?|seep(?:ing)?|weep(?:ing)?|oil\s+(?:on|under)|puddl\w*|fluid\s+(?:on|under))\b/i,
    ack: 'A leak like that is nearly always a seal, a gasket, or a fitting that has worked loose.',
    slots: [
      { id: 'location', priority: 10, known: (t) => has(LOCATION_RE, t),
        ask: () => 'where exactly is it coming from — the seal, a flange, a hose, or the casing itself' },
      { id: 'pattern', priority: 9, known: (t) => has(PATTERN_RE, t),
        ask: () => 'is it a steady drip, or only when it is running' },
    ],
    causes: [
      { label: 'Likely', text: 'Seal or gasket degradation' },
      { label: 'Likely', text: 'A fitting loosened by vibration' },
      { label: 'Possible', text: 'Overpressure or a blocked return path' },
    ],
    tests: [
      'Clean it, run it, and re-inspect to find the true origin rather than where it collects',
      'System pressure against the rated working pressure',
      'Fitting torque and line routing for chafe points',
    ],
    measurements: [['pressure', 'bar', PRESSURE_READING_RE]],
  },
  {
    key: 'no_start',
    label: 'the no-start',
    cues: /\b(won'?t\s+start|wont\s+start|not\s+starting|no\s+start|doesn'?t\s+(?:start|run)|does\s+not\s+(?:start|run)|\bdead\b|no\s+power)\b/i,
    ack: "A no-start is either the supply, a control interlock, or something's seized.",
    slots: [
      { id: 'detail', priority: 10, known: (t) => has(NO_START_DETAIL_RE, t),
        ask: () => 'does it hum or click when you try it, or is it completely silent — and any indicator lights' },
      { id: 'history', priority: 8, known: (t) => has(NO_START_HISTORY_RE, t),
        ask: () => 'did it run fine last time, or is this new' },
    ],
    causes: [
      { label: 'Likely', text: 'Supply not present at the terminals' },
      { label: 'Likely', text: 'Control-circuit interlock, E-stop or permissive not satisfied' },
      { label: 'Possible', text: 'Contactor or starter fault' },
      { label: 'Possible', text: 'Mechanical seizure preventing rotation' },
    ],
    tests: [
      'Supply voltage at the incoming terminals, using safe working practice',
      'Control-circuit interlocks and E-stop states in sequence',
      'Shaft rotation by hand with the machine isolated',
    ],
    measurements: [['voltage', 'V', VOLTAGE_READING_RE]],
    safetyHint: 'Isolate before checking rotation by hand.',
  },
  {
    key: 'error_code',
    label: 'the fault code',
    cues: /\b(error|fault\s*code|alarm|fault\b|flashing|blinking)\b/i,
    ack: 'That fault code will tell us exactly what tripped — I just need the details.',
    slots: [
      { id: 'code', priority: 10, known: (t) => has(ERROR_CODE_RE, t),
        ask: () => 'what is the exact code or text shown on the display' },
      { id: 'whenAppeared', priority: 8, known: (t) => has(WHEN_APPEARED_RE, t),
        ask: () => 'what was the machine doing when it appeared' },
    ],
    causes: [
      { label: 'Needs confirmation', text: 'The controller has latched a specific fault — its meaning is defined by the manufacturer’s code table' },
    ],
    tests: [
      'Read the exact code text from the display or nameplate label',
      'Look the code up in the manufacturer’s manual for this model',
    ],
    measurements: [],
  },
  {
    key: 'pressure',
    label: 'the pressure',
    cues: /\b(pressure|psi\b|\bbar\b|hydraulic|pneumatic|accumulator)\b/i,
    ack: 'A pressure problem like that is usually the seal, the relief setting, or a blockage.',
    slots: [
      { id: 'system', priority: 10, known: (t) => has(PRESSURE_SYSTEM_RE, t),
        ask: () => 'is this the hydraulic side, the pneumatic side, or a specific line' },
      { id: 'reading', priority: 9, known: (t) => has(PRESSURE_READING_RE, t),
        ask: () => 'what is the gauge reading, and what should it normally be' },
    ],
    causes: [
      { label: 'Likely', text: 'Relief or regulator drifted out of setting' },
      { label: 'Possible', text: 'Internal leakage past a worn seal' },
      { label: 'Possible', text: 'A restriction or blockage in the line' },
    ],
    tests: [
      'System pressure at the gauge against the rated working pressure',
      'Relief valve setting and condition',
      'Line and filter for restriction',
    ],
    measurements: [['pressure', 'bar', PRESSURE_READING_RE]],
    safetyHint: 'Depressurise and confirm zero at the gauge before breaking any joint.',
  },
  {
    key: 'smell',
    label: 'the smell',
    cues: /\b(smell\w*|od[o|u]r\w*|stink\w*)\b/i,
    ack: 'An odd smell is worth chasing down before it becomes something worse.',
    slots: [
      { id: 'smellType', priority: 10, known: (t) => has(SMELL_TYPE_RE, t),
        ask: () => 'what does it smell like — chemical, rubber, electrical, or something else' },
      { id: 'whenNoticed', priority: 8, known: (t) => has(WHEN_NOTICED_RE, t),
        ask: () => 'is it constant, or only when the machine is running' },
    ],
    causes: [
      { label: 'Possible', text: 'Overheating lubricant or a slipping belt' },
      { label: 'Possible', text: 'A chemical or coolant leak nearby' },
    ],
    tests: [
      'Trace the smell to its source with the machine running, from a safe distance',
      'Check lubricant condition and level',
    ],
    measurements: [],
  },
  {
    key: 'electrical_fault',
    label: 'the electrical fault',
    // Same cues as the hazard gate below — this topic only composes once the
    // gate's own required facts (energised state, location) are already known.
    cues: /\b(spark(?:s|ing)?|arc(?:ing)?|\bsmoke\b|smoking|scorch\w*|melt(?:ed|ing)?\s*(?:wire|insulation|plastic|cable)|exposed\s+(?:wire|conductor|terminal)|bare\s+(?:wire|conductor))\b|\bsmell\w*\b[\s\w]{0,20}\bburning\b|\bburning\b[\s\w]{0,20}\bsmell/i,
    ack: 'With the immediate hazard addressed —',
    slots: [],
    causes: [
      { label: 'Likely', text: 'Arcing at a loose or corroded connection — a terminal, contactor or cable joint' },
      { label: 'Likely', text: 'Damaged or overheating insulation breaking down under load' },
      { label: 'Possible', text: 'A failing internal component (capacitor or winding) shorting' },
    ],
    tests: [
      'Once proven isolated and dead, inspect the terminals and cable entry for scorch marks, discolouration or loose connections',
      'Check insulation resistance winding-to-earth before re-energising',
      'Do not re-energise until the source of the arcing or burning is found and corrected',
    ],
    measurements: [],
    safetyHint: 'Keep it isolated until the source is found and corrected.',
  },
]

function matchTopics(text: string): Topic[] {
  let matched = TOPICS.filter((t) => t.cues.test(text))
  // A burning smell is handled by the specific electrical-fault topic (and,
  // on the turn it's first mentioned, by the hazard gate below) — the
  // generic "unusual smell" topic would otherwise also match on the same
  // word and compete with it for which question gets asked.
  if (matched.some((t) => t.key === 'electrical_fault')) {
    matched = matched.filter((t) => t.key !== 'smell')
  }
  return matched
}

// ---------------------------------------------------------------- hazards

export interface Hazard {
  key: string
  title: string
  text: string
}

const HAZARD_ELECTRICAL_CUES =
  /\bspark(?:s|ing)?\b|\barc(?:ing)?\b|\bsmoke\b|smoking|scorch\w*|melt(?:ed|ing)?\s*(?:wire|insulation|plastic|cable)|exposed\s+(?:wire|conductor|terminal)|bare\s+(?:wire|conductor)|\bstill\s+live\b|\blive\s+wire\b|\bsmell\w*\b[\s\w]{0,20}\bburning\b|\bburning\b[\s\w]{0,20}\bsmell/i

/** Checked against the *current* message only — a safety banner shouldn't
 * keep re-firing on later turns that merely continue the same thread. */
export function matchHazard(text: string): Hazard | null {
  if (HAZARD_ELECTRICAL_CUES.test(text)) {
    return {
      key: 'electrical',
      title: 'Electrical hazard — stop before anything else.',
      text: 'Sparking, arcing, a burning smell or smoke can mean live conductors or failing '
        + 'insulation. Do not touch the unit or any cable until it is confirmed isolated.',
    }
  }
  return null
}

// ---------------------------------------------------------------- composing

function composeQuestion(clauses: string[]): string {
  const parts = clauses.filter(Boolean)
  if (!parts.length) return ''
  if (parts.length === 1) {
    const c = parts[0].charAt(0).toUpperCase() + parts[0].slice(1)
    return c.endsWith('?') ? c : `${c}?`
  }
  const joined = parts.map((c) => c.replace(/\?$/, '')).join(', and ')
  return joined.charAt(0).toUpperCase() + joined.slice(1) + '?'
}

export interface HazardGateResult {
  text: string
  notice: { level: 'safety'; title: string; text: string }
  followUps: string[]
}

/** Returns the safety-first response, or null when enough is already known
 * that the topic engine should take over (energised state + location). */
export function hazardGate(hazard: Hazard, allText: string): HazardGateResult | null {
  const energizedKnown = ENERGIZED_KNOWN_RE.test(allText)
  const locationKnown = HAZARD_LOCATION_RE.test(allText)
  if (energizedKnown && locationKnown) return null

  const clauses: string[] = []
  if (!energizedKnown) clauses.push('is the equipment currently energized, or has it been switched off and isolated')
  if (!locationKnown) clauses.push('where exactly is it coming from — the terminal box, a cable, or the motor/drive body itself')

  return {
    text: `That's a stop-first situation — let's make sure it's safe before anything else. ${composeQuestion(clauses)}`,
    notice: { level: 'safety', title: hazard.title, text: hazard.text },
    followUps: !energizedKnown ? ["It's still energized", "It's isolated / switched off"] : [],
  }
}

export interface ClarifyingResult {
  text: string
}

export interface DiagnosisResult {
  sections: Section[]
  confidence: number
  confidenceLabel: string
  safetyHint?: string
}

/** What this thread's accumulated text matches, and what (if anything) is
 * still missing before a real diagnosis can be composed. Shared by
 * planSteps() (for accurate work-trail labels) and answer() (for the reply
 * itself), so the two never disagree about what's actually happening. */
export function analyze(allText: string) {
  const topics = matchTopics(allText)
  const missingByTopic = topics.map((t) => ({
    topic: t,
    missing: t.slots.filter((s) => !s.known(allText)).sort((a, b) => b.priority - a.priority),
  }))
  const needsClarifying = missingByTopic.some((m) => m.missing.length > 0)
  return { topics, missingByTopic, needsClarifying }
}

/** At most two clarifying questions: the top two slots when only one topic
 * matched (go deep), or the single top slot from each matched topic when
 * several did (cover breadth) — either way, never re-ask something already
 * in the thread. */
export function pickClarifyingQuestion(missingByTopic: { topic: Topic; missing: Slot[] }[], allText: string): ClarifyingResult | null {
  const withMissing = missingByTopic.filter((m) => m.missing.length > 0)
  if (!withMissing.length) return null

  let clauses: string[]
  let ack: string
  if (withMissing.length === 1) {
    ack = withMissing[0].topic.ack
    clauses = withMissing[0].missing.slice(0, 2).map((s) => s.ask(allText))
  } else {
    ack = 'A few things are in play here — let’s narrow it down together.'
    clauses = withMissing.slice(0, 2).map((m) => m.missing[0].ask(allText))
  }
  return { text: `${ack} ${composeQuestion(clauses)}` }
}

export function composeDiagnosis(topics: Topic[], allText: string, machine: string): DiagnosisResult {
  const observed: string[] = []
  observed.push(`On ${machine}, you've described ${topics.map((t) => t.label).join(' and ')}.`)
  const loc = locOf(allText)
  if (loc) observed.push(`You placed it at the ${loc}.`)
  if (ONSET_RE.test(allText)) {
    const onsetSudden = /sudden|all\s+at\s+once|out\s+of\s+nowhere/i.test(allText)
    observed.push(`It started ${onsetSudden ? 'suddenly' : 'gradually'}.`)
  }

  const causes = topics.flatMap((t) => t.causes)
  const tests = Array.from(new Set(topics.flatMap((t) => t.tests))).slice(0, 5)
  const causesText = causes.map((c) => `${c.label}: ${c.text}.`).join(' ')
  const testsText = tests.map((t) => `${t}.`).join(' ')

  const needed: string[] = []
  for (const t of topics) {
    for (const [name, unit, re] of t.measurements) {
      if (!re.test(allText)) needed.push(`${name} (${unit})`)
    }
  }
  const uniqueNeeded = Array.from(new Set(needed))

  const sections: Section[] = [
    { kind: 'observed', text: observed.join(' ') },
    { kind: 'inferred', text: causesText },
    { kind: 'next', text: testsText },
  ]
  if (uniqueNeeded.length) {
    sections.push({ kind: 'measure', text: `Still to confirm: ${uniqueNeeded.join(', ')}.` })
  }

  const knownFactCount = topics.reduce((n, t) => n + t.slots.filter((s) => s.known(allText)).length, 0)
  const confidence = Math.min(0.85, 0.35 + knownFactCount * 0.12 + (topics.length > 1 ? 0.08 : 0))
  const confidenceLabel = confidence >= 0.7 ? 'Likely cause — needs confirmation'
    : confidence >= 0.5 ? 'Partly supported' : 'Weak evidence — needs confirmation'

  const safetyHint = topics.map((t) => t.safetyHint).find(Boolean)

  return { sections, confidence: Math.round(confidence * 100), confidenceLabel, safetyHint }
}
