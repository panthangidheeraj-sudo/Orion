/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Override the local backend origin, e.g. VITE_VF_BACKEND=http://127.0.0.1:9000 */
  readonly VITE_VF_BACKEND?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
