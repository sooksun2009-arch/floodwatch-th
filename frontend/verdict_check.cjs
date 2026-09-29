// A red verdict must never sit above a green "no reports" box.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const fails = []
const check = (n, ok, x = '') => { console.log((ok ? 'PASS  ' : 'FAIL  ') + n + (ok ? '' : `\n      -> ${x}`)); if (!ok) fails.push(n) }
;(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const p = await b.newPage()
  await p.setViewport({ width: 1400, height: 1000 })
  // Route through Lat Krabang, where the flooded-road feed has stretches.
  await p.setRequestInterception(true)
  p.on('request', (r) => {
    if (r.url().includes('/api/route/check') && r.method() === 'POST') {
      const body = JSON.parse(r.postData() || '{}')
      body.origin = { lat: 13.72, lng: 100.75 }; body.destination = { lat: 13.668, lng: 100.604 }
      delete body.origin_text; delete body.destination_text
      r.continue({ postData: JSON.stringify(body) })
    } else r.continue()
  })
  await p.goto(BASE, { waitUntil: 'domcontentloaded' })
  await p.waitForSelector('input', { timeout: 20000 })
  const inputs = await p.$$('input')
  await inputs[0].type('ลาดกระบัง'); await inputs[1].type('บางนา')
  await p.evaluate(() => [...document.querySelectorAll('button')].find((x) => x.textContent.includes('เช็คเส้นทางนี้'))?.click())
  await p.waitForFunction(() => document.body.innerText.includes('ถนนน้ำท่วมตามเส้นทาง') || document.body.innerText.includes('ไม่มีรายงานน้ำท่วมบนเส้นทางนี้'), { timeout: 60000 }).catch(() => {})
  const t = await p.evaluate(() => document.body.innerText)
  const red = /ไม่ควรไป|เสี่ยง/.test(t.slice(0, 4000))
  console.log('      verdict red:', red, '| roads:', t.includes('ถนนน้ำท่วมตามเส้นทาง'))
  check('เจอถนนน้ำท่วมตามเส้นทาง', t.includes('ถนนน้ำท่วมตามเส้นทาง'))
  check('คำตัดสินแดง -> ไม่มีกล่องเขียว "ไม่มีรายงานน้ำท่วมบนเส้นทางนี้"', !(red && t.includes('ไม่มีรายงานน้ำท่วมบนเส้นทางนี้')), 'ขัดกัน')
  check('แทนด้วยข้อความกลาง ๆ ว่ายังไม่มีผู้ใช้แจ้ง', t.includes('ยังไม่มีผู้ใช้แจ้งน้ำท่วมบนเส้นทางนี้'))
  check('ถนนน้ำท่วมขึ้นก่อนรายการรายงานผู้ใช้', t.indexOf('ถนนน้ำท่วมตามเส้นทาง') < t.indexOf('ยังไม่มีผู้ใช้แจ้งน้ำท่วม'))
  await p.screenshot({ path: process.argv[3] + '/verdict.png', fullPage: false })

  // The "ask about a detour" button must be understood by the assistant even
  // when an endpoint is a dropped pin or a GPS fix, not a place name.
  await p.evaluate(() => [...document.querySelectorAll('button')].find((x) => x.textContent.includes('ถามแชทบอท'))?.click())
  // Wait for the answer itself. The route panel also says "เส้นทาง", so a
  // body-text check passes the instant the chat opens and reads the greeting.
  await p.waitForFunction(() => {
    const leaves = [...document.querySelectorAll('div')].filter((d) => !d.children.length && d.innerText.trim())
    return leaves.slice(-10).some((d) => d.innerText.includes('→'))
  }, { timeout: 45000 }).catch(() => {})
  // Read the last bot bubble, not the whole page: the route panel also
  // contains the word "เส้นทาง", which made this pass or fail for the wrong
  // reason.
  // Read the last bot bubble, not the whole page: the route panel also
  // contains the word "เส้นทาง", which made this pass for the wrong reason.
  const chat = await p.evaluate(() => {
    const leaves = [...document.querySelectorAll('div')].filter((d) => !d.children.length && d.innerText.trim())
    return leaves.slice(-10).map((d) => d.innerText.trim()).join(' | ')
  })
  check('แชทตอบเรื่องเส้นทางที่เห็นอยู่', chat.includes(' → ') && chat.includes('เส้นทาง'), chat.slice(-400))
  check('ไม่ตอบว่า "ไม่แน่ใจว่าคุณหมายถึงที่ไหน"', !chat.includes('ผมไม่แน่ใจว่าคุณหมายถึงที่ไหน'))
  await b.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL VERDICT CHECKS PASSED'); process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
