import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Content-Security-Policy for the production build.
 *
 * The built app only ever needs: its own files, Google Fonts' stylesheet and
 * font files, and the Orion backend (API calls, document page images, voice
 * audio). Anything else — an injected <script>, a request to a stranger's
 * server — is refused by the browser, which limits the damage any future XSS
 * bug could do. The backend origin comes from the same VITE_VF_BACKEND value
 * api.ts uses, so the two can't disagree.
 *
 * Build-only: the dev server relies on inline scripts (React refresh) and a
 * websocket, which a strict policy would block.
 */
function contentSecurityPolicy(backendOrigin: string): Plugin {
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    // Components set inline style attributes; TextPressure injects a <style>.
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    `img-src 'self' data: blob: ${backendOrigin}`,
    `media-src 'self' blob: ${backendOrigin}`,
    `connect-src 'self' ${backendOrigin}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
  return {
    name: 'orion-csp',
    apply: 'build',
    transformIndexHtml(html) {
      return html.replace(
        '<meta charset="UTF-8" />',
        `<meta charset="UTF-8" />\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`,
      )
    },
  }
}

function originOf(url: string): string {
  try { return new URL(url).origin } catch { return 'http://127.0.0.1:8756' }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const backend = originOf(env.VITE_VF_BACKEND?.replace(/\/$/, '') || 'http://127.0.0.1:8756')
  return {
    plugins: [react(), contentSecurityPolicy(backend)],
    // Dev server on this machine only. It used to listen on every network
    // interface (host: true), exposing the dev server — and the Vite dev-server
    // file-access bugs — to anyone on the same Wi-Fi. To test on a phone,
    // opt in for that session: `npm run dev -- --host`.
    server: { host: 'localhost', port: 5173 },
    build: { target: 'es2020', outDir: 'dist', sourcemap: false },
  }
})
