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

export const timeAgo = (minutes) => {
  if (minutes == null) return ''
  if (minutes < 1) return 'เมื่อสักครู่'
  if (minutes < 60) return `${minutes} นาทีที่แล้ว`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} ชม.ที่แล้ว`
  return `${Math.floor(hours / 24)} วันที่แล้ว`
}
