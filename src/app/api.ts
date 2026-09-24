/**
 * Backend client.
 *
 * The real product talks to the local FastAPI service in `backend/`, which
 * owns all orchestration: model choice, tool calls, retrieval, memory and
 * safety. This file is the only place that knows the service exists.
 *
 * It degrades on purpose. If the service is not running — during design work,
 * on a machine where the models have not been exported, or while the backend
 * restarts — `probe()` returns false and the app falls back to the local
 * demo responder in `assistant.ts`. The UI shows which of the two answered,
 * so a demo can never accidentally pass off the stub as the real thing.
 */

import type { DocRef, Message, Mode, NoticeBlock, Section, SectionKind, Step } from './types'
import { uid } from './util'

const DEFAULT_BASE = 'http://127.0.0.1:8756'

export const BACKEND_BASE: string =
  import.meta.env.VITE_VF_BACKEND?.replace(/\/$/, '') || DEFAULT_BASE

/** What the backend says about itself — surfaced in Settings and About. */
export interface BackendInfo {
  online: boolean
  version?: string
  model?: { provider: string; model_id: string; accelerator: string; npu: boolean; synthetic: boolean }
  ready?: string[]
  unavailable?: string[]
  synthetic?: string[]
  npuClaim?: boolean
  reason?: string
}

export interface AskOptions {
  conversationId?: string
  imageIds?: string[]
  jobId?: string
  inspectionId?: string
  mode: Mode
  web: boolean
  profession?: string
  experience?: string
  /** Called as each real tool finishes, so the work trail shows what happened. */
  onStep?: (steps: Step[]) => void
  signal?: AbortSignal
}

export interface AskResult {
  message: Message
  conversationId: string
  degradedTools: string[]
  model?: BackendInfo['model']
}

let cached: BackendInfo = { online: false }

export function lastKnownBackend(): BackendInfo {
  return cached
}

/** Cheap liveness check. Never throws; a dead backend is a normal state. */
export async function probe(timeoutMs = 1500): Promise<BackendInfo> {
  const ctl = new AbortController()
  const timer = window.setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const health = await fetch(`${BACKEND_BASE}/api/health`, { signal: ctl.signal })
    if (!health.ok) throw new Error(`health ${health.status}`)

    const status = await fetch(`${BACKEND_BASE}/api/models/status`, { signal: ctl.signal })
    const body = status.ok ? await status.json() : null
    const reasoning = body?.roles?.reasoning

    cached = {
      online: true,
      version: '1.0.0',
      ready: body?.summary?.ready ?? [],
      unavailable: body?.summary?.unavailable ?? [],
      synthetic: body?.summary?.synthetic ?? [],
      npuClaim: Boolean(body?.summary?.npu_claim),
      model: reasoning
        ? {
            provider: reasoning.provider,
            model_id: reasoning.model_id,
            accelerator: reasoning.accelerator,
            npu: reasoning.npu,
            synthetic: reasoning.synthetic,
          }
        : undefined,
    }
  } catch (err) {
    cached = { online: false, reason: err instanceof Error ? err.message : 'unreachable' }
  } finally {
    window.clearTimeout(timer)
  }
  return cached
}

/* ------------------------------------------------------------------ chat */

/**
 * Ask the agent, streaming.
 *
 * The backend sends its work trail before any text, so `onStep` fires with
 * real tool results — "2 passages from your documents" — rather than the
 * invented timings the offline stub uses.
 */
export async function ask(text: string, opts: AskOptions): Promise<AskResult> {
  const res = await fetch(`${BACKEND_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: opts.signal,
    body: JSON.stringify({
      message: text,
      conversation_id: opts.conversationId,
      image_ids: opts.imageIds ?? [],
      job_id: opts.jobId,
      inspection_id: opts.inspectionId,
      mode: opts.mode,
      web: opts.web,
      profile: { profession: opts.profession, experience: opts.experience },
    }),
  })
  if (!res.ok || !res.body) throw new Error(`backend responded ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const steps: Step[] = []
  let buffer = ''
  let final: BackendResponse | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let cut: number
    while ((cut = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, cut).trim()
      buffer = buffer.slice(cut + 2)
      if (!frame.startsWith('data:')) continue
      const payload = frame.slice(5).trim()
      if (payload === '[DONE]') continue

      let event: StreamEvent
      try {
        event = JSON.parse(payload)
      } catch {
        continue
      }

      if (event.type === 'step') {
        steps.push({ icon: iconFor(event.tool), label: event.summary || event.tool, ms: event.duration_ms })
        opts.onStep?.([...steps])
      } else if (event.type === 'done') {
        final = event.result
      } else if (event.type === 'error') {
        throw new Error(event.reason || 'stream failed')
      }
    }
  }

  if (!final) throw new Error('the backend stream ended without a result')

  return {
    message: toMessage(final, opts.mode),
    conversationId: final.conversation_id,
    degradedTools: final.degraded_tools ?? [],
    model: final.model,
  }
}

/* -------------------------------------------------------------- uploads */

export interface UploadedDocument {
  documentId: string
  filename: string
  pageCount: number
  pagesRendered: number
  chunks: number
  state: string
  indexed: boolean
}

/** Send a manual, datasheet or schematic into the local knowledge vault. */
export async function uploadDocument(file: File, signal?: AbortSignal): Promise<UploadedDocument> {
  const form = new FormData()
  form.append('file', file, file.name)
  const res = await fetch(`${BACKEND_BASE}/api/documents/upload`, { method: 'POST', body: form, signal })
  const body = await res.json()
  if (!res.ok) throw new Error(body?.reason || `upload failed (${res.status})`)
  return {
    documentId: body.document_id,
    filename: body.filename,
    pageCount: body.page_count,
    pagesRendered: body.pages_rendered,
    chunks: body.index?.chunks ?? 0,
    state: body.state,
    indexed: Boolean(body.index?.chunks),
  }
}

/** Store a photo and get back the id the agent refers to it by. */
export async function uploadPhoto(blob: Blob, conversationId?: string): Promise<string> {
  const form = new FormData()
  form.append('file', blob, 'frame.jpg')
  if (conversationId) form.append('conversation_id', conversationId)
  const res = await fetch(`${BACKEND_BASE}/api/photo/upload`, { method: 'POST', body: form })
  const body = await res.json()
  if (!res.ok) throw new Error(body?.reason || `photo upload failed (${res.status})`)
  return body.image_id as string
}

export function documentPageUrl(documentId: string, page: number): string {
  return `${BACKEND_BASE}/api/documents/${documentId}/pages/${page}`
}

/* ------------------------------------------------------------ live mode */

export interface LiveSession {
  sessionId: string
  policy: { detect_interval_ms: number; ocr_interval_ms: number; vlm_min_gap_ms: number }
}

export async function liveStart(conversationId?: string, jobId?: string): Promise<LiveSession> {
  const res = await fetch(`${BACKEND_BASE}/api/live/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, job_id: jobId }),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body?.reason || 'could not start a live session')
  return { sessionId: body.session_id, policy: body.policy }
}

export interface LiveFrameResult {
  detections: Array<{ label: string; confidence: number; bbox: number[]; bbox_norm?: number[] }>
  textRegions: Array<{ text: string; confidence: number; bbox: number[] }>
  sceneChange: number
  ran: { detector: boolean; ocr: boolean; tracker: boolean; reasoning: boolean }
  reasons: string[]
  analysis: BackendResponse | null
}

/**
 * Send one frame. The backend decides what runs — §8 of the spec forbids
 * waking the reasoning model on every frame, so most calls return overlays
 * only, and `reasons` explains when it did wake.
 */
export async function liveFrame(
  sessionId: string,
  blob: Blob,
  opts: { question?: string; deep?: boolean; targetLabel?: string } = {},
): Promise<LiveFrameResult> {
  const form = new FormData()
  form.append('session_id', sessionId)
  form.append('file', blob, 'frame.jpg')
  if (opts.question) form.append('question', opts.question)
  if (opts.deep) form.append('deep', 'true')
  if (opts.targetLabel) form.append('target_label', opts.targetLabel)

  const res = await fetch(`${BACKEND_BASE}/api/live/frame`, { method: 'POST', body: form })
  const body = await res.json()
  if (!res.ok) throw new Error(body?.reason || `frame rejected (${res.status})`)
  return {
    detections: body.detections ?? [],
    textRegions: body.text_regions ?? [],
    sceneChange: body.scene_change ?? 0,
    ran: body.ran ?? { detector: false, ocr: false, tracker: false, reasoning: false },
    reasons: body.vlm?.reasons ?? [],
    analysis: body.analysis ?? null,
  }
}

export async function liveStop(sessionId: string): Promise<void> {
  const form = new FormData()
  form.append('session_id', sessionId)
  await fetch(`${BACKEND_BASE}/api/live/stop`, { method: 'POST', body: form })
}

/* ------------------------------------------------------- response mapping */

interface BackendSection { kind: string; title: string; items: string[] }
interface BackendRef {
  kind: string
  filename?: string
  page?: number
  excerpt?: string
  title?: string
  domain?: string
  memory_type?: string
}
interface BackendResponse {
  conversation_id: string
  message_id?: string | null
  text: string
  sections?: BackendSection[]
  notice?: { level: string; title: string; items: string[]; note?: string | null } | null
  question?: string | null
  refs?: BackendRef[]
  confidence?: number | null
  confidence_label?: string | null
  follow_ups?: string[]
  memory?: { stored?: boolean; reason?: string; pending_confirmation?: boolean } | null
  degraded_tools?: string[]
  model?: BackendInfo['model']
  error?: { error: string; reason: string } | null
}

type StreamEvent =
  | { type: 'start' }
  | { type: 'model' }
  | { type: 'step'; tool: string; ok: boolean; duration_ms: number; summary: string }
  | { type: 'text'; value: string }
  | { type: 'done'; result: BackendResponse }
  | { type: 'error'; reason?: string }

const SECTION_KINDS: SectionKind[] = ['observed', 'inferred', 'next', 'measure', 'ref']

function sectionKind(kind: string): SectionKind {
  return (SECTION_KINDS as string[]).includes(kind) ? (kind as SectionKind) : 'observed'
}

const NOTICE_LEVELS = ['safety', 'need', 'confirmed', 'error'] as const

function noticeOf(n: BackendResponse['notice']): NoticeBlock | undefined {
  if (!n) return undefined
  const level = (NOTICE_LEVELS as readonly string[]).includes(n.level)
    ? (n.level as NoticeBlock['level'])
    : 'need'
  const text = [...(n.items ?? []), n.note].filter(Boolean).join(' ')
  return { level, title: n.title, text }
}

function refsOf(refs: BackendRef[] | undefined): DocRef[] | undefined {
  if (!refs?.length) return undefined
  const out: DocRef[] = []
  for (const r of refs) {
    if (r.kind === 'document' || r.kind === 'document_page') {
      out.push({ doc: r.filename ?? 'document', page: r.page ?? 1, quote: r.excerpt ?? '' })
    } else if (r.kind === 'web') {
      out.push({ doc: r.title ?? r.domain ?? 'web source', page: 0, quote: r.domain ?? '' })
    } else if (r.kind === 'memory') {
      out.push({ doc: `memory · ${r.memory_type ?? 'job'}`, page: 0, quote: r.excerpt ?? '' })
    }
  }
  return out.length ? out : undefined
}

/** Backend response → the Message shape the UI already renders. */
function toMessage(body: BackendResponse, mode: Mode): Message {
  const sections: Section[] = []
  for (const s of body.sections ?? []) {
    const kind = sectionKind(s.kind)
    for (const item of s.items) sections.push({ kind, text: item })
  }

  let memory: string | undefined
  if (body.memory?.stored) memory = 'Saved to this job'
  else if (body.memory?.pending_confirmation) memory = 'Ready to save — confirm to keep it'

  return {
    id: body.message_id || uid('a'),
    role: 'assistant',
    at: Date.now(),
    mode,
    head: body.question ?? undefined,
    text: sections.length ? undefined : body.text,
    sections: sections.length ? sections : undefined,
    notice: noticeOf(body.notice),
    refs: refsOf(body.refs),
    confidence:
      typeof body.confidence === 'number' ? Math.round(body.confidence * 100) : undefined,
    confidenceLabel: body.confidence_label ?? undefined,
    memory,
    followUps: body.follow_ups?.length ? body.follow_ups : undefined,
  }
}

const STEP_ICONS: Record<string, string> = {
  vision_detect: 'eye',
  vision_segment: 'eye',
  vision_track: 'target',
  vision_classify: 'eye',
  ocr_extract: 'type',
  search_documents: 'search',
  get_document_page: 'file',
  get_document_metadata: 'file',
  list_documents: 'file',
  search_memory: 'clock',
  get_job_history: 'clock',
  web_search: 'globe',
  fetch_web_source: 'globe',
  ask_user: 'help',
  create_inspection_checklist: 'check',
  create_service_report: 'file',
}

function iconFor(tool: string): string {
  return STEP_ICONS[tool] ?? 'spark'
}
