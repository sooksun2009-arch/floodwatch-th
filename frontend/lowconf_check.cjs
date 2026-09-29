// A low-confidence stretch must not shout a level the verdict did not use.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const fails = []
const check = (n, ok, x = '') => { console.log((ok ? 'PASS  ' : 'FAIL  ') + n + (ok ? '' : `\n      -> ${x}`)); if (!ok) fails.push(n) }
const FAKE = {
  origin: { lat: 13.72, lng: 100.75 }, destination: { lat: 13.668, lng: 100.604 },
  verdict: 'risky', verdict_label: 'เสี่ยง มีจุดน้ำลึกที่รถเก๋งอาจไม่รอด', worst_level: 'deep',
  advice: 'ทดสอบ', recommendation: null, degraded: null, corridor_m: 150,
  roads_attribution: 'ข้อมูลถนนน้ำท่วม: Floodboard (floodboard.org), CC BY 4.0',
  routes: [{
    label: 'เส้นทางหลัก', distance_km: 10, duration_min: 20, is_straight_line: false,
    verdict: 'risky', verdict_label: 'เสี่ยง', worst_level: 'deep', is_recommended: true,
    path: [[13.72, 100.75], [13.668, 100.604]], obstacles: [], cameras: [], stations: [],
    roads: [
      { along_km: 5.3, name: 'ซอยไม่มั่นใจ', name_en: '', depth_cm: null, closed: false,
        sedan: 'risky', motorbike: 'risky', conf: 0.32, confident: false, estimated: true,
        sources: ['crowd'], updated: Date.now(), level: 'shallow', length_m: 20 },
      { along_km: 8.4, name: 'ถนนมั่นใจ', name_en: '', depth_cm: 40, closed: false,
        sedan: 'blocked', motorbike: 'blocked', conf: 0.9, confident: true, estimated: false,
        sources: ['bma_sensor'], updated: Date.now(), level: 'severe', length_m: 179 },
    ],
  }],
}
;(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const p = await b.newPage()
  await p.setViewport({ width: 430, height: 950, isMobile: true, hasTouch: true })
  await p.setRequestInterception(true)
  p.on('request', (r) => {
    if (r.url().includes('/api/route/check') && r.method() === 'POST') {
      return r.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE) })
    }
    r.continue()
  })
  await p.goto(BASE, { waitUntil: 'domcontentloaded' })
  await p.waitForSelector('input', { timeout: 30000 })
  const ins = await p.$$('input')
  await ins[0].type('ก'); await ins[1].type('ข')
  await p.evaluate(() => [...document.querySelectorAll('button')].find((x) => x.textContent.includes('เช็คเส้นทางนี้'))?.click())
  await p.waitForFunction(() => document.body.innerText.includes('ซอยไม่มั่นใจ'), { timeout: 30000 }).catch(() => {})
  const t = await p.evaluate(() => document.body.innerText)
  const block = t.slice(t.indexOf('ซอยไม่มั่นใจ'), t.indexOf('ถนนมั่นใจ'))
  console.log('      จุดไม่มั่นใจแสดงว่า:', block.replace(/\n/g, ' | ').trim())
  check('จุดไม่มั่นใจ: พาดหัวบอกระดับที่นับจริง ("ระวัง")', block.includes('นับเป็น "ระวัง"'), block)
  check('จุดไม่มั่นใจ: ไม่พาดหัวว่า "รถเก๋ง: เสี่ยง" อีก', !block.includes('รถเก๋ง: เสี่ยง'), block)
  check('จุดไม่มั่นใจ: ยังบอกว่า Floodboard ว่าอย่างไร', block.includes('Floodboard ระบุ'), block)
  check('จุดไม่มั่นใจ: ยังบอกเปอร์เซ็นต์ความมั่นใจ', block.includes('32%'), block)
  const conf = t.slice(t.indexOf('ถนนมั่นใจ'))
  check('จุดที่มั่นใจ: ยังแสดงแบบเดิม (รถเก๋ง: ผ่านไม่ได้)', conf.includes('รถเก๋ง: ผ่านไม่ได้'), conf.slice(0, 200))
  await p.evaluate(() => {
    const el = [...document.querySelectorAll('p')].find((x) => x.textContent.includes('ซอยไม่มั่นใจ'))
    el?.scrollIntoView({ block: 'center' })
  })
  await new Promise((r) => setTimeout(r, 400))
  await p.screenshot({ path: process.argv[3] + '/lowconf.png' })
  await b.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL LOW-CONFIDENCE LABEL CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
