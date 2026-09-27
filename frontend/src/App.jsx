import { Suspense, lazy } from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
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

function Nav() {
  const { user, logout, isModerator } = useAuth()
  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-2 px-3 py-2.5 sm:px-4">
        <Link to="/" className="mr-1 flex items-center gap-2 font-bold">
          <span className="text-xl">🌊</span>
          <span className="hidden sm:inline">FloodWatch TH</span>
        </Link>
        <nav className="flex flex-1 items-center gap-0.5 overflow-x-auto">
          <NavLink to="/" className={tabClass} end>
            เช็คเส้นทาง
          </NavLink>
          <NavLink to="/cameras" className={tabClass}>
            กล้อง CCTV
          </NavLink>
          <NavLink to="/stats" className={tabClass}>
            ภาพรวม
          </NavLink>
          {isModerator && (
            <NavLink to="/admin" className={tabClass}>
              ผู้ดูแล
            </NavLink>
          )}
        </nav>
        {user ? (
          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden text-sm text-slate-400 sm:inline">
              {user.display_name || user.username}
            </span>
            <button onClick={logout} className="text-sm text-slate-400 hover:text-slate-200">
              ออก
            </button>
          </div>
        ) : (
          <Link to="/login" className="shrink-0 text-sm text-slate-300 hover:text-white">
            เข้าสู่ระบบ
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
