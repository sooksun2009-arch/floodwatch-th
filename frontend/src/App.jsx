import { Suspense, lazy, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { useT } from './i18n'
import Home from './pages/Home'

// Admin and stats are rarely opened and pull in extra code; loading them on
// demand keeps the first paint of the route checker small.
const Cameras = lazy(() => import('./pages/Cameras'))
const Stats = lazy(() => import('./pages/Stats'))
const Login = lazy(() => import('./pages/Login'))
const Admin = lazy(() => import('./pages/Admin'))

const tabClass = ({ isActive }) =>
  `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'
  }`

const SHARE = {
  th: {
    title: 'FloodWatch TH — เช็คน้ำท่วมก่อนออกรถ',
    text: 'เช็คว่าเส้นทางที่จะไปมีน้ำท่วมไหม จากรายงานของคนในพื้นที่ เครื่องวัดระดับน้ำ และเรดาร์ฝน',
  },
  en: {
    title: 'FloodWatch TH — check Thai roads for flooding before you drive',
    text: 'See whether your route is flooded, from local reports, water-level gauges and rain radar.',
  },
}

/**
 * Thai and English, side by side rather than behind a menu.
 *
 * A visitor who cannot read the interface cannot find a control described in
 * words they cannot read, so both labels are always on screen and the active
 * one is simply marked.
 */
function LangToggle() {
  const { lang, setLang, t } = useT()
  return (
    <div
      className="flex shrink-0 overflow-hidden rounded-lg border border-slate-700 text-xs font-semibold"
      role="group"
      aria-label={t('lang.label')}
    >
      {[['th', 'ไทย'], ['en', 'EN']].map(([code, label]) => (
        <button
          key={code}
          onClick={() => setLang(code)}
          aria-pressed={lang === code}
          lang={code}
          className={`px-2 py-1.5 transition-colors ${
            lang === code
              ? 'bg-slate-700 text-white'
              : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function ShareButton() {
  // Two mechanisms, because they fail in different places. navigator.share
  // opens the phone's own sheet — which on a Thai phone means LINE, where
  // this actually gets passed around — but it does not exist on most
  // desktops. Clipboard is the desktop answer and can be refused outright
  // in a non-secure context or by policy, so neither is assumed.
  const [said, setSaid] = useState(null)
  const { lang, t } = useT()
  const shareText = SHARE[lang] || SHARE.th

  // Always the app's front door, never the page in the address bar: sharing
  // /admin or a half-filled form helps nobody.
  const url = typeof window === 'undefined' ? '' : window.location.origin

  const flash = (message) => {
    setSaid(message)
    setTimeout(() => setSaid(null), 2200)
  }

  const share = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ ...shareText, url })
        return
      } catch (error) {
        // Dismissing the sheet is a choice, not a failure.
        if (error?.name === 'AbortError') return
      }
    }
    try {
      await navigator.clipboard.writeText(`${shareText.title}
${url}`)
      flash(t('share.copied'))
    } catch {
      // Last resort: put it somewhere it can be copied by hand.
      flash(url)
    }
  }

  return (
    <div className="relative shrink-0">
      <button
        onClick={share}
        className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-sm text-slate-300 transition-colors hover:bg-slate-800 hover:text-white"
        title={t('nav.share')}
      >
        <span aria-hidden="true">🔗</span>
        <span className="hidden sm:inline">{t('nav.share')}</span>
        <span className="sr-only">{t('nav.share')}</span>
      </button>
      {said && (
        <span
          role="status"
          className="absolute right-0 top-full z-40 mt-1.5 whitespace-nowrap rounded-lg border border-emerald-800 bg-emerald-950/95 px-2.5 py-1.5 text-xs text-emerald-200 shadow-lg backdrop-blur"
        >
          {said}
        </span>
      )}
    </div>
  )
}

function Nav() {
  const { user, logout, isModerator } = useAuth()
  const { t } = useT()
  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-2 px-3 py-2.5 sm:px-4">
        <Link to="/" className="mr-1 flex items-center gap-2 font-bold">
          <span className="text-xl">🌊</span>
          <span className="hidden sm:inline">FloodWatch TH</span>
        </Link>
        <nav className="flex flex-1 items-center gap-0.5 overflow-x-auto">
          <NavLink to="/" className={tabClass} end>
            {t('nav.route')}
          </NavLink>
          <NavLink to="/cameras" className={tabClass}>
            {t('nav.cameras')}
          </NavLink>
          <NavLink to="/stats" className={tabClass}>
            {t('nav.stats')}
          </NavLink>
          {isModerator && (
            <NavLink to="/admin" className={tabClass}>
              {t('nav.admin')}
            </NavLink>
          )}
        </nav>
        <LangToggle />
        <ShareButton />
        {user ? (
          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden text-sm text-slate-400 sm:inline">
              {user.display_name || user.username}
            </span>
            <button onClick={logout} className="text-sm text-slate-400 hover:text-slate-200">
              {t('nav.logout')}
            </button>
          </div>
        ) : (
          <Link to="/login" className="shrink-0 text-sm text-slate-300 hover:text-white">
            {t('nav.login')}
          </Link>
        )}
      </div>
    </header>
  )
}

function RequireModerator({ children }) {
  const { user, loading, isModerator } = useAuth()
  if (loading) return <div className="p-8 text-center text-slate-400">กำลังโหลด…</div>
  if (!user) return <Navigate to="/login" replace />
  if (!isModerator) {
    return (
      <div className="p-8 text-center text-slate-400">
        บัญชีนี้ไม่มีสิทธิ์เข้าหน้าผู้ดูแลระบบ
      </div>
    )
  }
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <div className="flex min-h-screen flex-col">
        <Nav />
        <main className="flex-1">
          <Suspense fallback={<div className="p-8 text-center text-slate-400">กำลังโหลด…</div>}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/cameras" element={<Cameras />} />
              <Route path="/stats" element={<Stats />} />
              <Route path="/login" element={<Login />} />
              <Route
                path="/admin"
                element={
                  <RequireModerator>
                    <Admin />
                  </RequireModerator>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </AuthProvider>
  )
}
