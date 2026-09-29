/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Override the local backend origin, e.g. VITE_VF_BACKEND=http://127.0.0.1:9000 */
  readonly VITE_VF_BACKEND?: string
  /* Firebase Web app config (from .env.local — never committed). Optional:
     without them Orion runs exactly as before, local-only. */
  readonly VITE_FIREBASE_API_KEY?: string
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string
  readonly VITE_FIREBASE_PROJECT_ID?: string
  readonly VITE_FIREBASE_STORAGE_BUCKET?: string
  readonly VITE_FIREBASE_MESSAGING_SENDER_ID?: string
  readonly VITE_FIREBASE_APP_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
