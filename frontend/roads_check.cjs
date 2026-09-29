// Local check: Floodboard flooded-road layer, its popup, legend, toggle, and
// the flooded-roads list in a route result.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const SHOTS = process.argv[3] || '.'
const fails = []
const check = (name, ok, extra = '') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : `\n      -> ${extra}`))
  if (!ok) fails.push(name)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1400, height: 900 })
  const roadCalls = []
  page.on('response', (r) => {
    if (r.url().includes('/api/flood-roads')) roadCalls.push({ status: r.status(), enc: r.headers()['content-encoding'] })
  })
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => window.__fwMap?.loaded?.(), { timeout: 30000 }).catch(() => {})
  // Bangkok east, where the feed has data.
  await page.evaluate(() => window.__fwMap.jumpTo({ center: [100.75, 13.72], zoom: 14 }))
  await page.waitForFunction(
    () => window.__fwMap.queryRenderedFeatures({ layers: ['flood-roads-line'] }).length > 0,
    { timeout: 60000 }).catch(() => {})
  // The source's loaded data is internal to MapLibre; ask the endpoint instead.
  const count = await page.evaluate(() => fetch('/api/flood-roads').then((r) => r.json()).then((j) => j.features.length))
  check('โหลดถนนน้ำท่วมเมื่อแผนที่อยู่แถว กทม.', count > 100, count)
  check('ส่งแบบบีบอัด gzip', roadCalls.some((c) => c.status === 200 && c.enc === 'gzip'), JSON.stringify(roadCalls))
  await sleep(1500)
  const rendered = await page.evaluate(() => window.__fwMap.queryRenderedFeatures({ layers: ['flood-roads-line'] }).length)
  check('เส้นถนนแสดงบนแผนที่', rendered > 0, rendered)

  // Click a rendered road away from any pin.
  const opened = await page.evaluate(() => {
    const map = window.__fwMap
    const feats = map.queryRenderedFeatures({ layers: ['flood-roads-line'] })
    for (const f of feats) {
      const c = f.geometry.type === 'MultiLineString' ? f.geometry.coordinates[0][0] : f.geometry.coordinates[0]
      const point = map.project(c)
      if (map.queryRenderedFeatures(point, { layers: ['report-dots', 'station-dots'] }).length) continue
      const hit = map.queryRenderedFeatures(point, { layers: ['flood-roads-line'] })
      if (!hit.length) continue
      map.fire('click', { point, lngLat: map.unproject(point), originalEvent: new MouseEvent('click') })
      return true
    }
    return false
  })
  await sleep(600)
  const popup = await page.evaluate(() => document.querySelector('.maplibregl-popup-content')?.textContent || '')
  check('แตะเส้นถนนแล้วขึ้นรายละเอียด', opened && popup.includes('รถเก๋ง') && popup.includes('Floodboard'), popup.slice(0, 200))
  await page.screenshot({ path: `${SHOTS}/roads-map.png` })

  const attribution = await page.evaluate(() => document.querySelector('.maplibregl-ctrl-attrib')?.textContent || '')
  check('ให้เครดิต Floodboard ที่มุมแผนที่', attribution.includes('Floodboard'), attribution)
  const legend = await page.evaluate(() => document.body.innerText)
  check('คำอธิบายสีมีส่วนถนนน้ำท่วม', legend.includes('ช่วงถนนน้ำท่วม') && legend.includes('ปิดทุกคัน'))

  // Toggle off hides the layer.
  await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('ถนนน้ำท่วม') && b.hasAttribute('aria-pressed'))?.click())
  await sleep(500)
  const vis = await page.evaluate(() => window.__fwMap.getLayoutProperty('flood-roads-line', 'visibility'))
  check('ปิดปุ่ม -> ซ่อนชั้นถนน', vis === 'none', vis)

  // Route check through Lat Krabang via the API the page uses.
  const route = await page.evaluate(async () => {
    const r = await fetch('/api/route/check', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ origin: { lat: 13.72, lng: 100.75 }, destination: { lat: 13.668, lng: 100.604 } }),
    })
    const j = await r.json()
    return { status: r.status, verdict: j.verdict, roads: j.routes?.[0]?.roads?.length, attribution: j.roads_attribution, straight: j.routes?.[0]?.is_straight_line }
  })
  console.log('      route:', JSON.stringify(route))
  check('เช็คเส้นทางได้', route.status === 200, route.status)
  if (!route.straight) {
    check('เส้นทางผ่านลาดกระบังเจอถนนน้ำท่วม', route.roads > 0, JSON.stringify(route))
    check('มีเครดิตในคำตอบ', (route.attribution || '').includes('CC BY'), route.attribution)
  } else {
    console.log('      (routing server not reachable locally: straight line, road matching not exercised)')
  }

  await browser.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL FLOOD-ROAD UI CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
