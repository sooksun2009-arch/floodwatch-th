// A disputed pin stays on the map and says so.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const fails = []
const check = (n, ok, x = '') => { console.log((ok ? 'PASS  ' : 'FAIL  ') + n + (ok ? '' : `\n      -> ${x}`)); if (!ok) fails.push(n) }
;(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const p = await b.newPage()
  await p.setViewport({ width: 1400, height: 900 })
  await p.goto(BASE, { waitUntil: 'domcontentloaded' })
  await p.waitForFunction(() => window.__fwMap?.loaded?.(), { timeout: 30000 }).catch(() => {})

  // Make a report, then have three strangers say the water has gone.
  const rid = await p.evaluate(async () => {
    // A photo is required on public reports, so make one.
    const canvas = document.createElement('canvas')
    canvas.width = 80
    canvas.height = 60
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#3b6ea5'
    ctx.fillRect(0, 0, 80, 60)
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.8))
    const form = new FormData()
    form.append('file', new File([blob], 'test.jpg', { type: 'image/jpeg' }))
    const up = await fetch('/api/uploads', { method: 'POST', body: form })
    if (!up.ok) return null
    const photo = (await up.json()).url
    const mk = await fetch('/api/reports', { method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ lat: 13.7461, lng: 100.5341, level: 'severe', depth_cm: 70,
                             place: 'ถนนทดสอบ กลั่นแกล้ง ปากซอย 9', photo_url: photo }) })
    const j = await mk.json()
    return j.id || null
  })
  check('สร้างรายงานทดสอบได้', Boolean(rid), rid)

  const votes = []
  for (let i = 0; i < 3; i++) {
    votes.push(await p.evaluate(async (id, ip) => {
      const r = await fetch(`/api/reports/${id}/vote`, { method: 'POST',
        headers: { 'content-type': 'application/json', 'x-forwarded-for': ip },
        body: JSON.stringify({ vote: 'dispute' }) })
      return r.status
    }, rid, `8.8.8.${i}`))
  }
  check('โหวตแย้ง 3 ครั้งผ่าน', votes.every((s) => s === 200), votes.join(','))

  const state = await p.evaluate(async (id) => (await fetch(`/api/reports/${id}`)).json(), rid)
  check('หมุดยังอยู่ ไม่ถูกลบ', state.status === 'approved' && state.needs_review === true, state)

  // Reload so the map picks the flag up, then open that pin.
  await p.reload({ waitUntil: 'domcontentloaded' })
  await p.waitForFunction(() => window.__fwMap?.loaded?.(), { timeout: 30000 }).catch(() => {})
  await new Promise((r) => setTimeout(r, 2500))
  const opened = await p.evaluate((id) => {
    const map = window.__fwMap
    const f = map.queryRenderedFeatures({ layers: ['report-dots'] }).find((x) => x.properties.id === id)
    if (!f) return false
    const point = map.project(f.geometry.coordinates)
    map.fire('click', { lngLat: map.unproject(point), point, features: [f],
                        originalEvent: new MouseEvent('click') })
    return true
  }, rid)
  await new Promise((r) => setTimeout(r, 700))
  const popup = await p.evaluate(() => document.querySelector('.maplibregl-popup-content')?.textContent || '')
  check('หมุดยังแตะเปิดได้บนแผนที่', opened, 'ไม่พบหมุดบนแผนที่')
  check('popup เตือนว่ามีผู้แย้ง และยังไม่ยืนยันว่าผ่านได้',
    popup.includes('มีผู้แย้งว่าน้ำลดแล้ว') && popup.includes('ยังไม่ยืนยันว่าผ่านได้'), popup.slice(0, 260))
  await p.screenshot({ path: process.argv[3] + '/disputed-pin.png' })

  await b.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL DISPUTE-UI CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
