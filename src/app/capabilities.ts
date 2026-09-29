import type { BackendInfo } from './api'
import { speechSupported } from './speech'

export type CapState = 'ready' | 'busy' | 'off' | 'error'

export interface Capability {
  key: 'backend' | 'ai' | 'camera' | 'voice' | 'web'
  label: string
  state: CapState
  word: string
  detail: string
}

/**
 * What this running copy of Orion can actually do right now.
 *
 * Every state here is earned from something measured at runtime — the
 * backend's own `/api/models/status` report, or a real browser API check —
 * never from what the product was designed to do. In particular, "Local AI
 * ready" needs the backend to report its reasoning role as loaded AND not a
 * deterministic stand-in. A hosted deployment without an exported model will
 * therefore honestly read "Local AI unavailable".
 */
export function systemCapabilities(backend: BackendInfo, webSearch: boolean): Capability[] {
  const checking = backend.checked === false

  const backendCap: Capability = checking
    ? { key: 'backend', label: 'Backend', state: 'busy', word: 'Checking', detail: 'Contacting the backend…' }
    : backend.locked
      ? { key: 'backend', label: 'Backend', state: 'error', word: 'Locked', detail: 'The backend is running but needs its access key — enter it below.' }
      : backend.online
      ? { key: 'backend', label: 'Backend', state: 'ready', word: 'Online', detail: 'The Orion backend answered its health check.' }
      : { key: 'backend', label: 'Backend', state: 'error', word: 'Offline', detail: 'The backend did not answer — the built-in demo responder is being used.' }

  const model = backend.model
  const aiReady = backend.online
    && Boolean(model)
    && !model?.synthetic
    && (backend.ready ?? []).includes('reasoning')
    && !(backend.synthetic ?? []).includes('reasoning')
  const aiCap: Capability = checking
    ? { key: 'ai', label: 'Local AI', state: 'busy', word: 'Checking', detail: 'Waiting for the backend’s model report…' }
    : aiReady
      ? {
          key: 'ai', label: 'Local AI', state: 'ready', word: 'Ready',
          detail: `${model!.model_id} · ${model!.provider} · ${model!.npu ? 'NPU' : model!.accelerator.toUpperCase()}`,
        }
      : {
          key: 'ai', label: 'Local AI', state: 'error', word: 'Unavailable',
          detail: backend.locked
            ? 'Locked — the backend’s model can’t be used until the access key is entered.'
            : !backend.online
            ? 'No backend is reachable, so no local model is running.'
            : model?.synthetic
              ? `${model.model_id} is a deterministic stand-in, not a language model.`
              : backend.modelReason
                // Verbatim from /api/models/status — e.g. "asset installed, but local
                // GenieX/QAIRT NPU execution requires a Windows ARM64 Snapdragon machine".
                ? `${model?.model_id && model.model_id !== 'none' ? `${model.model_id} not running: ` : 'No reasoning model loaded: '}${backend.modelReason}`
                : 'The backend reports no reasoning model loaded.',
        }

  const hasCamera = typeof navigator !== 'undefined'
    && typeof window !== 'undefined'
    && window.isSecureContext
    && Boolean(navigator.mediaDevices?.getUserMedia)
  const cameraCap: Capability = hasCamera
    ? { key: 'camera', label: 'Camera', state: 'ready', word: 'Ready', detail: 'This browser can open the camera.' }
    : { key: 'camera', label: 'Camera', state: 'error', word: 'Unavailable', detail: 'Camera access needs HTTPS and a browser with camera support.' }

  const onDeviceStt = (backend.ready ?? []).includes('stt')
  const voiceCap: Capability = onDeviceStt
    ? { key: 'voice', label: 'Voice', state: 'ready', word: 'Ready', detail: 'Speech recognition runs in the backend.' }
    : speechSupported()
      ? { key: 'voice', label: 'Voice', state: 'ready', word: 'Ready', detail: 'Using this browser’s speech recognition.' }
      : { key: 'voice', label: 'Voice', state: 'error', word: 'Unavailable', detail: 'No speech recognition in this browser or the backend.' }

  const webCap: Capability = webSearch
    ? { key: 'web', label: 'Web search', state: 'ready', word: 'On', detail: 'Used only after manuals and memory.' }
    : { key: 'web', label: 'Web search', state: 'off', word: 'Off', detail: 'Manuals and memory only.' }

  return [backendCap, aiCap, cameraCap, voiceCap, webCap]
}
