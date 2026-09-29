// One-off local check: survey card, source label, admin tallies + CSV download.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const SHOTS = process.argv[3] || '.'
const fails = []
const check = (name, ok, extra = '') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : `\n      -> ${extra}`))
  if (!ok) fails.push(name)
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true })
  // Facebook in-app browser, and a two-minute wait squeezed to half a second.
  await page.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile [FBAN/FBIOS;FBAV/450.0]')
  await page.evaluateOnNewDocument(() => {
    const real = window.setTimeout
    window.setTimeout = (fn, ms, ...rest) => real(fn, ms === 120000 ? 500 : ms, ...rest)
  })
  const sent = []
  page.on('request', (r) => {
    if (r.url().includes('/api/visits') && r.method() === 'POST') sent.push(r.postData())
  })
  await page.goto(BASE, { waitUntil: 'networkidle2' })
  await page.waitForFunction(() => document.body.innerText.includes('ช่วยตอบ 2 ข้อ'), { timeout: 8000 })
    .catch(() => {})

  const shown = await page.evaluate(() => document.body.innerText.includes('ช่วยตอบ 2 ข้อ'))
  check('แบบสอบถามขึ้นหลังรอ', shown)
  await page.screenshot({ path: `${SHOTS}/survey-mobile.png` })
  const click = (text) => page.evaluate((t) => {
    const b = [...document.querySelectorAll('[role=dialog] button')].find((x) => x.textContent.trim() === t)
    b?.click()
    return Boolean(b)
  }, text)
  check('เลือก "ขับส่งของ"', await click('ขับส่งของ / รับจ้าง'))
  check('เลือกอายุ 25–34', await click('25–34'))
  check('กดส่ง', await click('ส่ง'))
  await new Promise((r) => setTimeout(r, 800))
  check('ขึ้นข้อความขอบคุณ', await page.evaluate(() => document.body.innerText.includes('ขอบคุณครับ 🙏')))
  const survey = sent.find((b) => b && b.includes('"use"'))
  check('ส่งคำตอบไปเซิร์ฟเวอร์', survey === '{"use":"delivery","age":"25_34"}', survey)

  await page.reload({ waitUntil: 'networkidle2' })
  await new Promise((r) => setTimeout(r, 1500))
  check('ตอบแล้ว เปิดใหม่ไม่ถามซ้ำ',
    !(await page.evaluate(() => document.body.innerText.includes('ช่วยตอบ 2 ข้อ'))))

  // Admin view.
  const login = await page.evaluate(async () => {
    const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'admin1234' }) })
    const j = await r.json()
    localStorage.setItem('floodwatch_token', j.access_token)
    return r.status
  })
  check('ล็อกอินแอดมิน', login === 200, login)
  await page.setViewport({ width: 1280, height: 1800 })
  await page.goto(`${BASE}/admin`, { waitUntil: 'networkidle2' })
  await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'ผู้เข้าชม')?.click())
  await page.waitForFunction(() => document.body.innerText.includes('สำรองข้อมูล'), { timeout: 8000 }).catch(() => {})
  const text = await page.evaluate(() => document.body.innerText)
  const src = await page.evaluate(async () => {
    const r = await fetch('/api/visits/summary',
      { headers: { Authorization: `Bearer ${localStorage.getItem('floodwatch_token')}` } })
    return (await r.json()).tallies.source
  })
  // sendBeacon bodies are invisible to puppeteer, so read the server's count.
  check('เซิร์ฟเวอร์นับแหล่งที่มาเป็น facebook (UA แอป FB)',
    src.some((x) => x.key === 'facebook' && x.count > 0) && !src.some((x) => x.key.includes('http')),
    JSON.stringify(src))
  check('หน้าแอดมินมีส่วนแหล่งที่มา', text.includes('มาจากช่องทางไหน') && text.includes('Facebook'), text.slice(0, 300))
  check('หน้าแอดมินมีผลสำรวจ', text.includes('แบบสอบถาม: ใช้ทำอะไร') && text.includes('ขับส่งของ'))
  check('หน้าแอดมินมีจังหวัด', text.includes('จังหวัดที่ถูกค้นเส้นทาง'))
  check('มีปุ่มดาวน์โหลด CSV', text.includes('รายงานน้ำท่วมทั้งหมด'))
  await page.screenshot({ path: `${SHOTS}/admin-visits.png`, fullPage: true })

  const csv = await page.evaluate(async () => {
    const r = await fetch('/api/admin/export/reports.csv',
      { headers: { Authorization: `Bearer ${localStorage.getItem('floodwatch_token')}` } })
    const buf = new Uint8Array(await r.arrayBuffer())
    return { status: r.status, bom: buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf,
      head: new TextDecoder().decode(buf.slice(0, 300)) }
  })
  check('ดาวน์โหลด CSV ผ่านหน้าเว็บได้ มี BOM', csv.status === 200 && csv.bom, JSON.stringify(csv).slice(0, 200))

  await browser.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL SURVEY/ADMIN CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
