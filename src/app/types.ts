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
export interface NoticeBlock { level: NoticeLevel; title: string; text: string }

export interface Evidence { id: string; caption: string; url?: string }
export interface DocRef { doc: string; page: number; quote: string }

export interface Message {
  id: string
  role: 'user' | 'assistant'
  at: number
  mode: Mode
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

export interface Prefs {
  reduceMotion: boolean
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
