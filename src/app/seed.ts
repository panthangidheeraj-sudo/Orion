import type { Conversation, VFile, Profile, Access, Prefs } from './types'

export const DEFAULT_PROFILE: Profile = {
  name: '',
  age: '',
  profession: '',
  experience: '',
  site: '',
}

export const DEFAULT_ACCESS: Access = {
  identity: true,
  experience: true,
  age: false,
  history: true,
}

export const DEFAULT_PREFS: Prefs = {
  reduceMotion: false,
  webSearch: false,
  onboarded: false,
}

const DAY = 86_400_000
const now = Date.now()

export const SEED_FILES: VFile[] = [
  {
    id: 'f-manual',
    name: 'Siemens 1LE1 Maintenance.pdf',
    kind: 'pdf',
    size: 12_400_000,
    state: 'ready',
    progress: 100,
    pages: 184,
    addedAt: now - 7 * DAY,
  },
  {
    id: 'f-schematic',
    name: 'Site P-12 schematic.pdf',
    kind: 'pdf',
    size: 2_100_000,
    state: 'ready',
    progress: 100,
    pages: 6,
    addedAt: now - 2 * DAY,
  },
  {
    id: 'f-datasheet',
    name: 'Bearing datasheet 6308.pdf',
    kind: 'pdf',
    size: 820_000,
    state: 'ready',
    progress: 100,
    pages: 4,
    addedAt: now - 17 * DAY,
  },
]

export const SEED_CONVERSATIONS: Conversation[] = [
  {
    id: 'c-motor04',
    title: 'Cooling fan vibration — Motor #04',
    machine: 'Motor #04',
    startedAt: now - 7 * DAY,
    openedAt: now - 7 * DAY,
    fileIds: ['f-manual'],
    messages: [
      {
        id: 'm1',
        role: 'user',
        at: now - 7 * DAY,
        mode: 'normal',
        text: 'Motor #04 is vibrating again and the drive end feels hot.',
      },
      {
        id: 'm2',
        role: 'assistant',
        at: now - 7 * DAY + 4000,
        mode: 'normal',
        head: 'Analysed 2 frames · manual matched · 1.4 s',
        sections: [
          {
            kind: 'observed',
            text: 'The drive-end bearing housing is running at 71 °C against 46 °C on the fan end, and the vibration is strongest along the shaft axis.',
          },
          {
            kind: 'inferred',
            text: 'Drive-end bearing degradation, most likely lubricant breakdown rather than misalignment — the coupling faces are still parallel.',
          },
          {
            kind: 'next',
            text: 'Take an axial vibration reading at the drive-end housing at full load. Above 7.1 mm/s RMS the bearing is at replacement threshold under ISO 10816-3.',
          },
        ],
        refs: [{ doc: 'Siemens 1LE1 — Maintenance', page: 42, quote: 'bearing limits' }],
        confidence: 72,
        confidenceLabel: 'Likely cause — needs confirmation',
        notice: {
          level: 'safety',
          title: 'Lock out the drive before touching the housing.',
          text: 'Surface temperature is above 70 °C. Let it cool or use a non-contact probe for the reading.',
        },
      },
    ],
  },
  {
    id: 'c-pump',
    title: 'Pump seal weep — Bay 3',
    machine: 'Pump B3-02',
    startedAt: now - 8 * DAY,
    openedAt: now - 6 * DAY,
    fileIds: [],
    messages: [
      {
        id: 'p1',
        role: 'user',
        at: now - 8 * DAY,
        mode: 'normal',
        text: 'Weep from the pump seal in bay 3, roughly a drip a minute.',
      },
      {
        id: 'p2',
        role: 'assistant',
        at: now - 8 * DAY + 3000,
        mode: 'normal',
        head: 'Answered from your manuals · 0.8 s',
        sections: [
          { kind: 'observed', text: 'A drip a minute at the gland is above the 6 drops/minute guidance for a packed seal.' },
          { kind: 'next', text: 'Retorque the gland follower a sixth of a turn, run for ten minutes and re-count the drips before replacing anything.' },
        ],
      },
    ],
  },
]
