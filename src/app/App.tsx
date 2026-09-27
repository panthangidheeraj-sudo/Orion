import { Starfield } from '../ui/Starfield'
import { Logo, TabBar, TopBar } from '../ui/TopBar'
import { Icon } from '../ui/Icon'
import { useStore } from './store'
import { Home } from '../screens/Home'
import { Convo } from '../screens/Convo'
import { Chat } from '../screens/Chat'
import { Live } from '../screens/Live'
import { Files } from '../screens/Files'
import { DocViewer } from '../screens/DocViewer'
import { Reports } from '../screens/Reports'
import { Settings } from '../screens/Settings'
import { About } from '../screens/About'
import { Onboarding } from '../screens/Onboarding'

function Toasts() {
  const { toasts, dismiss } = useStore()
  if (!toasts.length) return null
  return (
    <div className="toast-wrap" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div className="toast" key={t.id}>
          <Icon name="check" size={19} stroke="#0b7a52" width={2.1} />
          <div style={{ flex: 1 }}>
            <b>{t.title}</b>
            {t.detail && <div><span>{t.detail}</span></div>}
          </div>
          <button
            type="button" className="ibtn plain sm" aria-label="Dismiss"
            style={{ color: 'var(--vf-on-invert)' }}
            onClick={() => dismiss(t.id)}
          >
            <Icon name="x" size={15} width={1.8} />
          </button>
        </div>
      ))}
    </div>
  )
}

export function App() {
  const { route, prefs } = useStore()
  // Live Mode replaces the starfield with the camera experience.
  const starfield = route !== 'live'
  const showTabbar = route !== 'onboarding' && route !== 'live'

  return (
    <div className="vf-app">
      {starfield ? <Starfield reduceMotion={prefs.reduceMotion} /> : <div className="vf-stage"><div className="vf-vig" /></div>}

      {/* `has-tabbar` is what reserves room for the fixed phone tab bar: the
          frame's bottom padding becomes --vf-nav-reserve (tab bar height +
          its offset + the safe-area inset), so no screen can scroll content
          underneath it. Screens without the tab bar get the plain inset. */}
      <div className={['vf-frame', route === 'chat' && 'chat-frame', showTabbar && 'has-tabbar', `route-${route}`].filter(Boolean).join(' ')}>
        {route !== 'onboarding' && <Logo />}
        {route !== 'onboarding' && <TopBar />}

        {/* `key={route}` remounts this wrapper on every navigation (and on the
            very first paint after a refresh), so the `vf-enter` fade/slide-in
            — the same entrance every panel and card in the app uses — plays
            for whichever screen is now showing. Reduce Motion silences it via
            the global kill-switch below, same as everywhere else. */}
        <div
          key={route}
          className="vf-enter"
          style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto', minHeight: 0 }}
        >
          {route === 'home' && <Home />}
          {route === 'convo' && <Convo />}
          {route === 'chat' && <Chat />}
          {route === 'live' && <Live />}
          {route === 'files' && <Files />}
          {route === 'doc' && <DocViewer />}
          {route === 'reports' && <Reports />}
          {route === 'settings' && <Settings />}
          {route === 'about' && <About />}
          {route === 'onboarding' && <Onboarding />}
        </div>

        {showTabbar && <TabBar />}
      </div>

      <Toasts />
    </div>
  )
}
