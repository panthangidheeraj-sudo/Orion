export type Mode = 'normal' | 'live'

export type Route =
  | 'home' | 'convo' | 'chat' | 'live' | 'files' | 'doc'
  | 'reports' | 'settings' | 'about' | 'onboarding'

export type FileState = 'uploading' | 'reading' | 'indexing' | 'ready' | 'failed'
export type FileKind = 'pdf' | 'image' | 'text' | 'other'

export interface VFile {
  id: string
  name: string
  kind: FileKind
  size: number
  state: FileState
  progress: number
  pages?: number
  addedAt: number
  url?: string
  note?: string
  /** Set once the local backend has ingested and indexed this file. */
  docId?: string
  /** Pages the backend actually rendered, as opposed to the estimate. */
  indexedChunks?: number
}

export type SectionKind = 'observed' | 'inferred' | 'next' | 'measure' | 'ref'
export interface Section { kind: SectionKind; text: string }

export type NoticeLevel = 'safety' | 'need' | 'confirmed' | 'error'
export interface NoticeBlock {
  level: NoticeLevel
  title: string
  text: string
  /** Raised by the backend's safety gate: rendered before everything else. */
  first?: boolean
}

export interface Evidence { id: string; caption: string; url?: string }
export interface DocRef { doc: string; page: number; quote: string }

/**
 * How an assistant turn should be rendered — decided by the backend's router,
 * never by the client:
 *  - conversation: ordinary chat, plain prose
 *  - clarify:      one natural question (ambiguous request, or the technical
 *                  workflow needs a specific detail)
 *  - diagnosis:    the full technician answer with sections and evidence
 *  - fallback:     no language model was available to understand the message
 *  - offline:      the Orion engine itself could not be reached
 */
export type MessageKind = 'conversation' | 'clarify' | 'diagnosis' | 'fallback' | 'offline'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  at: number
  mode: Mode
  kind?: MessageKind
  text?: string
  head?: string
  attachments?: string[]
  sections?: Section[]
  notice?: NoticeBlock
  evidence?: Evidence[]
  refs?: DocRef[]
  confidence?: number
  confidenceLabel?: string
  memory?: string
  followUps?: string[]
}

export interface Conversation {
  id: string
  title: string
  machine?: string
  startedAt: number
  openedAt: number
  messages: Message[]
  fileIds: string[]
}

export interface Profile {
  name: string
  age: string
  profession: string
  experience: string
  site: string
}

export interface Access {
  identity: boolean
  experience: boolean
  age: boolean
  history: boolean
}

export type Theme = 'dark' | 'light'

export interface Prefs {
  reduceMotion: boolean
  /** Appearance. Absent in prefs saved before light mode existed → dark. */
  theme?: Theme
  webSearch: boolean
  onboarded: boolean
}

/** One step of the assistant's visible work trail. */
export interface Step {
  icon: string
  label: string
  ms: number
}

export interface Detection {
  id: string
  label: string
  confidence: number
  /** percentages of the camera frame, so overlays survive any aspect ratio */
  x: number
  y: number
  w: number
  h: number
  tone: 'neutral' | 'warn' | 'selected'
}

export interface OcrTag { id: string; x: number; y: number; label: string; value: string }
