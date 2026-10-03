// While the gauge feed is down the card must say "unknown", never "all clear".
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const fails = []
const check = (n, ok, x = '') => { console.log((ok ? 'PASS  ' : 'FAIL  ') + n + (ok ? '' : `\n      -> ${x}`)); if (!ok) fails.push(n) }
const mk = (name, status, extra = {}) => ({
  id: name, name_th: name, name_en: name, lat: 14.35, lng: 100.57,
  reports: 0, worst_level: null, impassable: 0, overflowing: 0, stations: 0, cameras: 0,
  raining: null, stations_total: 20, overflowing_last_known: 0, status, ...extra,
})
const BODY = {
  provinces: [mk('พระนครศรีอยุธยา', 'unknown', { overflowing_last_known: 9 }), mk('ระยอง', 'normal', { stations: 4 })],
  rain_known: false, generated_at: 0, gauge_age_hours: 33, stale_after_hours: 6,
}
;(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const p = await b.newPage()
  await p.setViewport({ width: 430, height: 900, isMobile: true, hasTouch: true })
  await p.setRequestInterception(true)
  p.on('request', (r) => r.url().includes('/api/stats/provinces-overview')
    ? r.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(BODY) })
    : r.continue())
  await p.goto(BASE, { waitUntil: 'domcontentloaded' })
  await p.evaluate(() => localStorage.setItem('floodwatch.province', 'พระนครศรีอยุธยา'))
  await p.reload({ waitUntil: 'domcontentloaded' })
  await p.waitForFunction(() => document.body.innerText.includes('📍 พระนครศรีอยุธยา'), { timeout: 30000 })
  const head = await p.evaluate(() => document.querySelector('[aria-expanded]').innerText)
  check('หัวการ์ด: "ไม่ทราบสถานการณ์" ไม่ใช่ "ยังไม่พบรายงาน"',
    head.includes('ไม่ทราบสถานการณ์') && !head.includes('ยังไม่พบรายงาน'), head)
  await p.evaluate(() => document.querySelector('[aria-expanded]').click())
  await new Promise((r) => setTimeout(r, 400))
  const t = await p.evaluate(() => document.body.innerText)
  check('บอกว่าไม่อัปเดตมากี่ชั่วโมง', t.includes('ไม่ได้อัปเดตมา 33 ชม.'), t.slice(0, 400))
  check('บอกค่าครั้งสุดท้าย (ล้นตลิ่ง 9) ในฐานะอดีต', t.includes('ครั้งสุดท้ายที่วัดได้ ล้นตลิ่ง 9 สถานี'))
  check('เตือนว่าไม่ได้แปลว่าปลอดภัย', t.includes('ไม่ได้แปลว่าปลอดภัย'))
  check('ไม่พูดว่า "ไม่พบสถานีวัดน้ำล้นตลิ่ง" (ซึ่งไม่ทราบ)', !t.includes('ไม่พบสถานีวัดน้ำล้นตลิ่ง'))
  const dot = await p.evaluate(() => document.querySelector('[aria-expanded] span')?.className || '')
  check('จุดสีเทา ไม่ใช่เขียว', dot.includes('slate') && !dot.includes('emerald'), dot)
  await p.screenshot({ path: process.argv[3] + '/card-unknown.png' })

  // And a province with live gauges is still allowed to be calm.
  await p.evaluate(() => localStorage.setItem('floodwatch.province', 'ระยอง'))
  await p.reload({ waitUntil: 'domcontentloaded' })
  await p.waitForFunction(() => document.body.innerText.includes('📍 ระยอง'), { timeout: 30000 })
  const calm = await p.evaluate(() => document.querySelector('[aria-expanded]').innerText)
  check('จังหวัดที่เครื่องวัดสด -> ยังเป็น "ยังไม่พบรายงาน" ได้', calm.includes('ยังไม่พบรายงาน'), calm)
  await b.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL OUTAGE-CARD CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
