// Single place that talks to the backend. Everything else calls these helpers,
// so auth headers and error shapes are handled once.

const TOKEN_KEY = 'floodwatch_token'

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null // private mode / blocked storage
  }
}

export const setToken = (token) => {
  try {
    token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable — the session simply lasts until reload */
  }
}

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function request(path, { method = 'GET', body, form, headers = {}, signal } = {}) {
  const token = getToken()
  const init = { method, headers: { ...headers }, signal }

  if (token) init.headers.Authorization = `Bearer ${token}`
  if (form) {
    init.body = form // browser sets the multipart boundary itself
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  const resp = await fetch(path, init)
  if (resp.status === 204) return null

  const text = await resp.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }

  if (!resp.ok) {
    // FastAPI reports validation errors as a list of objects; flatten them into
    // one readable Thai sentence rather than showing "[object Object]".
    let detail = data?.detail ?? data
    if (Array.isArray(detail)) {
      detail = detail.map((d) => d.msg || JSON.stringify(d)).join(', ')
    } else if (detail && typeof detail === 'object') {
      detail = JSON.stringify(detail)
    }
    throw new ApiError(detail || `คำขอล้มเหลว (${resp.status})`, resp.status, data)
  }
  return data
}

const qs = (params) => {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const str = search.toString()
  return str ? `?${str}` : ''
}

export const api = {
  health: () => request('/api/health'),

  login: (username, password) =>
    request('/api/auth/login', { method: 'POST', body: { username, password } }),
  register: (payload) => request('/api/auth/register', { method: 'POST', body: payload }),
  me: () => request('/api/auth/me'),

  reports: (params) => request(`/api/reports${qs(params)}`),
  report: (id) => request(`/api/reports/${id}`),
  createReport: (payload) => request('/api/reports', { method: 'POST', body: payload }),
  voteReport: (id, vote) =>
    request(`/api/reports/${id}/vote`, { method: 'POST', body: { vote } }),
  myReports: () => request('/api/reports/mine/list'),

  cameras: (params) => request(`/api/cameras${qs(params)}`),
  createCamera: (payload) => request('/api/cameras', { method: 'POST', body: payload }),
  updateCamera: (id, payload) =>
    request(`/api/cameras/${id}`, { method: 'PATCH', body: payload }),
  deleteCamera: (id) => request(`/api/cameras/${id}`, { method: 'DELETE' }),
  cameraHealthCheck: () => request('/api/cameras/health-check', { method: 'POST' }),

  checkRoute: (payload, signal) =>
    request('/api/route/check', { method: 'POST', body: payload, signal }),
  geocode: (q, signal) => request(`/api/route/geocode${qs({ q })}`, { signal }),

  chat: (payload) => request('/api/chat', { method: 'POST', body: payload }),
  chatStarters: () => request('/api/chat/starters'),

  stations: (params) => request(`/api/stations${qs(params)}`),
  stationSummary: () => request('/api/stations/summary'),
  stationHistory: (id) => request(`/api/stations/${encodeURIComponent(id)}/history`),
  rainStatus: () => request('/api/rain/status'),
  rainCameras: () => request('/api/rain/cameras'),
  syncStations: () => request('/api/stations/sync', { method: 'POST' }),

  provinces: () => request('/api/areas/provinces'),
  summary: () => request('/api/stats/summary'),
  byProvince: () => request('/api/stats/by-province'),
  timeline: (hours) => request(`/api/stats/timeline${qs({ hours })}`),

  upload: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/uploads', { method: 'POST', form })
  },

  queue: () => request('/api/admin/queue'),
  // Moderators need to see what is live, not only what is waiting — taking a
  // wrong report off the map matters more than approving a new one.
  liveReports: () => request('/api/reports?limit=500'),
  moderate: (id, payload) =>
    request(`/api/admin/reports/${id}/moderate`, { method: 'POST', body: payload }),
  users: () => request('/api/admin/users'),
  updateUser: (id, payload) =>
    request(`/api/admin/users/${id}`, { method: 'PATCH', body: payload }),
  audit: () => request('/api/admin/audit'),

  importPaste: (payload) => request('/api/import/paste', { method: 'POST', body: payload }),
  importFile: (file, { sourceName, autoApprove, dryRun }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('source_name', sourceName)
    form.append('auto_approve', String(autoApprove))
    form.append('dry_run', String(dryRun))
    return request('/api/import/file', { method: 'POST', form })
  },
}

// ---------------------------------------------------------------- shared vocab

export const LEVELS = {
  normal: { label: 'สัญจรได้ปกติ', color: '#16a34a', short: 'ปกติ' },
  puddle: { label: 'น้ำขังผิวถนน ไม่เกิน 10 ซม.', color: '#65a30d', short: 'น้ำขัง' },
  shallow: { label: 'น้ำท่วม 10-30 ซม.', color: '#eab308', short: '10-30 ซม.' },
  deep: { label: 'น้ำท่วม 30-60 ซม.', color: '#f97316', short: '30-60 ซม.' },
  severe: { label: 'น้ำท่วมเกิน 60 ซม.', color: '#dc2626', short: 'เกิน 60 ซม.' },
  closed: { label: 'ปิดการจราจร', color: '#7f1d1d', short: 'ปิดถนน' },
}

export const VERDICTS = {
  clear: { label: 'ไปได้', tone: 'bg-emerald-600', ring: 'ring-emerald-500/30', icon: '✓' },
  caution: { label: 'ไปได้ ระวัง', tone: 'bg-amber-500', ring: 'ring-amber-500/30', icon: '!' },
  risky: { label: 'เสี่ยง', tone: 'bg-orange-600', ring: 'ring-orange-500/30', icon: '!' },
  blocked: { label: 'ไม่ควรไป', tone: 'bg-red-700', ring: 'ring-red-500/30', icon: '✕' },
}

// Gauge situation levels from the national water data centre (1 = critically
// low, 5 = over the bank). Only 4 and 5 matter for flooding.
export const SITUATIONS = {
  1: { label: 'น้ำน้อยวิกฤต', color: '#a16207' },
  2: { label: 'น้ำน้อย', color: '#ca8a04' },
  3: { label: 'ปกติ', color: '#16a34a' },
  4: { label: 'เฝ้าระวัง น้ำมาก', color: '#f97316' },
  5: { label: 'วิกฤต น้ำล้นตลิ่ง', color: '#dc2626' },
}

export const situationColor = (level) => SITUATIONS[level]?.color || '#64748b'

export const levelColor = (level) => LEVELS[level]?.color || '#64748b'
export const levelLabel = (level) => LEVELS[level]?.label || level || 'ไม่ระบุ'

/**
 * A photo URL that is safe to hand to an <img src>.
 *
 * The server is the real gate — it stores a photo_url only when its own upload
 * endpoint minted it — but this stays as a second line, because every screen
 * that renders a report photo would otherwise have to remember the rule, and
 * one that forgets turns a report into a request the viewer's browser makes on
 * a stranger's behalf. Relative uploads and https both pass; anything else,
 * including javascript: and protocol-relative //host, does not.
 */
export const safePhotoUrl = (url) => {
  if (typeof url !== 'string') return null
  if (url.startsWith('/uploads/')) return url
  if (url.startsWith('https://')) return url
  return null
}

// ---------------------------------------------------------------- coordinates

// Thailand's bounding box, so a pasted number from somewhere else is rejected
// rather than dropping a flood pin in the wrong country.
const TH_BOUNDS = { minLat: 5.4, maxLat: 20.6, minLng: 97.2, maxLng: 105.7 }

const inThailand = (lat, lng) =>
  lat >= TH_BOUNDS.minLat && lat <= TH_BOUNDS.maxLat &&
  lng >= TH_BOUNDS.minLng && lng <= TH_BOUNDS.maxLng

const dmsToDecimal = (deg, min, sec, hemisphere) => {
  const value = Number(deg) + Number(min) / 60 + Number(sec) / 3600
  return /[SW]/i.test(hemisphere) ? -value : value
}

/**
 * Pull a coordinate pair out of whatever someone pasted.
 *
 * Mirrors the importer on the server, which was written against the shapes
 * Thai agency reports actually use: a decimal pair, the degrees/minutes/seconds
 * form Google Maps displays, and the several URL forms it produces when you
 * copy a pin. Returns null when nothing usable is in there.
 */
export const parseCoords = (text) => {
  if (!text) return null
  const input = String(text).normalize('NFKC')

  // 13°41'11.3"N 100°38'06.7"E
  const dms = input.match(
    /(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['′]\s*([\d.]+)\s*["″]?\s*([NSns])[,\s]+(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['′]\s*([\d.]+)\s*["″]?\s*([EWew])/,
  )
  if (dms) {
    const lat = dmsToDecimal(dms[1], dms[2], dms[3], dms[4])
    const lng = dmsToDecimal(dms[5], dms[6], dms[7], dms[8])
    return inThailand(lat, lng) ? { lat, lng } : null
  }

  const patterns = [
    /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/,                                  // maps place data
    /@(-?\d+\.\d+),(-?\d+\.\d+)/,                                      // /maps/@lat,lng,17z
    /[?&](?:q|query|ll|destination)=(-?\d+\.\d+)%2C(-?\d+\.\d+)/i,     // url-encoded comma
    /[?&](?:q|query|ll|destination)=(-?\d+\.\d+),\s*(-?\d+\.\d+)/i,
    /(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{2,3}\.\d{3,})/,                 // plain pair
  ]
  for (const pattern of patterns) {
    const match = input.match(pattern)
    if (match) {
      const lat = Number(match[1])
      const lng = Number(match[2])
      if (inThailand(lat, lng)) return { lat, lng }
    }
  }
  return null
}

/**
 * How a report's age should read on screen.
 *
 * From a user: "จุดน้ำท่วมมันเปลี่ยนกันเป็นชั่วโมง ถ้าหมุดบอกด้วยว่ารายงานเข้ามา
 * เมื่อไหร่ คนดูจะกล้าตัดสินใจออกรถกว่าเยอะ" — the age is not a footnote, it is
 * most of what makes the rest of the pin worth acting on. Water moves in about
 * an hour, so these bands are in hours, and an old pin says so in a colour
 * rather than leaving someone to do the arithmetic and hope.
 *
 * The oldest band asks for a vote instead of only warning, because the person
 * reading it is usually standing where the answer is.
 */
export const reportAge = (minutes) => {
  if (minutes == null) return null
  const ago = timeAgo(minutes)
  if (minutes < 45) {
    return { text: `แจ้งเมื่อ ${ago}`, color: '#34d399', note: null }
  }
  if (minutes < 150) {
    return { text: `แจ้งเมื่อ ${ago}`, color: '#fbbf24', note: 'สถานการณ์อาจเปลี่ยนแล้ว' }
  }
  return {
    text: `แจ้งเมื่อ ${ago}`,
    color: '#f87171',
    note: 'นานแล้ว — ถ้าคุณอยู่แถวนั้น ช่วยกดยืนยันหน่อยครับ',
  }
}

export const timeAgo = (minutes) => {
  if (minutes == null) return ''
  if (minutes < 1) return 'เมื่อสักครู่'
  if (minutes < 60) return `${minutes} นาทีที่แล้ว`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} ชม.ที่แล้ว`
  return `${Math.floor(hours / 24)} วันที่แล้ว`
}
