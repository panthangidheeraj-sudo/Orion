import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { StoreProvider } from './app/store'
import { App } from './app/App'
import './styles/tokens.css'
import './styles/app.css'
import { applyTheme } from './app/util'

// Apply the saved Appearance before React's first paint, so a light-mode user
// never sees a flash of the dark theme on load. (An inline <script> in
// index.html would do this earlier, but the production CSP forbids inline
// scripts.)
try {
  const saved = JSON.parse(localStorage.getItem('vf.prefs') || '{}') as { theme?: string }
  applyTheme(saved.theme === 'light' ? 'light' : 'dark')
} catch {
  /* storage blocked: stay dark */
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </StrictMode>,
)
