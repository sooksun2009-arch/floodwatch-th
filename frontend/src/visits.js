/**
 * Tells the server that someone opened the app, and nothing else about them.
 *
 * The site promises not to store the routes people search or keep a travel
 * history, so this sends a page *label* — "map", "cameras" — never a path or a
 * query string, which could carry where somebody was trying to get to.
 *
 * Whether this browser is new today is decided here rather than on the server,
 * because it is the only arrangement where the server keeps nothing per
 * visitor: it remembers its own last counted date and says yes once a day. A
 * cleared browser counts again, so the unique figure is a floor. That is the
 * right way round for a number nobody is billed on.
 */
const DAY_KEY = 'floodwatch.counted'

// Made up per tab, held in the page and never stored. It exists so the server
// can answer "how many are here now" from memory and forget on restart.
const token = Math.random().toString(36).slice(2, 14)

const today = () => new Date().toISOString().slice(0, 10)

function firstToday() {
  try {
    if (localStorage.getItem(DAY_KEY) === today()) return false
    localStorage.setItem(DAY_KEY, today())
    return true
  } catch {
    // Private window or blocked storage: count the view, claim no more than
    // that. Better to undercount visitors than to invent them.
    return false
  }
}

const pageOf = (pathname) => {
  if (pathname.startsWith('/cameras')) return 'cameras'
  if (pathname.startsWith('/stats')) return 'stats'
  if (pathname.startsWith('/admin')) return 'admin'
  if (pathname.startsWith('/login')) return 'login'
  return pathname === '/' ? 'map' : 'other'
}

const post = (path, body) => {
  try {
    const payload = JSON.stringify(body)
    // sendBeacon survives the page being closed, which a fetch does not.
    if (navigator.sendBeacon) {
      navigator.sendBeacon(path, new Blob([payload], { type: 'application/json' }))
      return
    }
    fetch(path, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: payload,
      keepalive: true,
    }).catch(() => {})
  } catch {
    // Counting is the least important thing this app does. It never gets to
    // break anything, and it never gets to show an error.
  }
}

export function countVisit(pathname) {
  post('/api/visits', { page: pageOf(pathname), first_today: firstToday(), token })
}

/** Keeps "here now" true while a tab is open, without counting again. */
export function startHeartbeat() {
  const beat = () => {
    if (document.visibilityState === 'visible') post('/api/visits/ping', { token })
  }
  const timer = setInterval(beat, 45000)
  document.addEventListener('visibilitychange', beat)
  return () => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', beat)
  }
}
