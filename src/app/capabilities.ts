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
  const connecting = backend.checked === false
  const waking = Boolean(backend.waking) && !backend.locked
  // Not answering yet, inside the cold-start window (a hosted backend waking
  // from sleep or restarting after a deploy) — not yet a real "offline".
  const checking = connecting || waking

  const backendCap: Capability = connecting
    ? { key: 'backend', label: 'Backend', state: 'busy', word: 'Connecting', detail: 'Contacting the backend…' }
    : waking && !backend.online
      ? { key: 'backend', label: 'Backend', state: 'busy', word: 'Waking', detail: 'The hosted backend is waking up (it sleeps when idle, or is restarting after an update). Retrying every few seconds — this can take up to a minute.' }
    : backend.locked
      ? { key: 'backend', label: 'Backend', state: 'error', word: 'Locked', detail: 'The backend is running but needs its access key — enter it below.' }
      : backend.online
      ? { key: 'backend', label: 'Backend', state: 'ready', word: 'Online', detail: 'The Orion backend answered its health check.' }
      : {
          key: 'backend', label: 'Backend', state: 'error', word: 'Offline',
          detail: `The backend did not answer${backend.reason ? ` (${backend.reason})` : ''}, even after about a minute and a half of retries — the built-in demo responder is being used. Orion keeps checking every 30 seconds and will reconnect on its own.`,
        }

  const model = backend.model
  const aiReady = backend.online
    && Boolean(model)
    && !model?.synthetic
    && (backend.ready ?? []).includes('reasoning')
    && !(backend.synthetic ?? []).includes('reasoning')
  // Hosted AI (the Render deployment) is named as such and never described as
  // on-device or as running on the NPU; the backend already reports npu=false.
  const hosted = aiReady ? Boolean(model?.hosted) : /hosted/i.test(backend.aiConfigured ?? '')
  const aiLabel = hosted ? 'Hosted AI' : 'Local AI'
  const aiCap: Capability = checking
    ? {
        key: 'ai', label: /hosted/i.test(backend.aiConfigured ?? '') ? 'Hosted AI' : 'Local AI', state: 'busy',
        word: backend.online ? 'Connecting' : 'Waiting',
        detail: backend.online ? 'The backend is up — waiting for its model report…' : 'Waiting for the backend to wake…',
      }
    : aiReady
      ? {
          key: 'ai', label: aiLabel, state: 'ready', word: 'Ready',
          detail: hosted
            ? `${model!.model_id} · hosted inference — runs on the provider’s servers, not on this device or a Snapdragon NPU. Photos you send are uploaded for that turn.`
            : `${model!.model_id} · ${model!.provider} · ${model!.npu ? 'NPU' : model!.accelerator.toUpperCase()}`,
        }
      : {
          key: 'ai', label: aiLabel, state: 'error', word: 'Unavailable',
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
