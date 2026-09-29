// Local check for the "your area" card on a real phone viewport.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const SHOTS = process.argv[3] || '.'
const fails = []
const check = (name, ok, extra = '') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : `\n      -> ${extra}`))
  if (!ok) fails.push(name)
}
const RAYONG = { latitude: 12.6814, longitude: 101.2816 }

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  })
  await browser.defaultBrowserContext().overridePermissions(new URL(BASE).origin, ['geolocation'])
  const page = await browser.newPage()
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true })
  await page.setGeolocation(RAYONG)
  const leaked = []
  page.on('request', (r) => {
    const body = `${r.url()} ${r.postData() || ''}`
    if (body.includes('12.68') || body.includes('101.28')) leaked.push(r.url())
  })
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.body.innerText.includes('พื้นที่ของคุณ'), { timeout: 20000 })
    .catch(() => {})
  check('ยังไม่เลือก -> ขึ้นแถบ "พื้นที่ของคุณ"',
    await page.evaluate(() => document.body.innerText.includes('พื้นที่ของคุณ')))

  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes('ใช้ตำแหน่งของฉัน'))
    b?.click()
    return Boolean(b)
  })
  check('มีปุ่มใช้ตำแหน่งของฉัน', clicked)
  await page.waitForFunction(() => document.body.innerText.includes('📍 ระยอง'), { timeout: 10000 })
    .catch(() => {})
  check('หาจังหวัดจากตำแหน่งได้ (ระยอง)',
    await page.evaluate(() => document.body.innerText.includes('📍 ระยอง')))
  await new Promise((r) => setTimeout(r, 2500))
  const center = await page.evaluate(() => window.__fwMap?.getCenter())
  check('แผนที่บินไปที่ระยอง',
    center && Math.abs(center.lat - 12.7) < 0.5 && Math.abs(center.lng - 101.3) < 0.6,
    JSON.stringify(center))
  check('พิกัดไม่ถูกส่งออกจากเครื่อง', leaked.length === 0, leaked.join(' '))
  await page.screenshot({ path: `${SHOTS}/area-collapsed.png` })

  await page.evaluate(() => document.querySelector('[aria-expanded]')?.click())
  await new Promise((r) => setTimeout(r, 400))
  const text = await page.evaluate(() => document.body.innerText)
  check('กดแล้วขยายรายละเอียด', text.includes('ดูบนแผนที่'), text.slice(0, 200))
  await page.screenshot({ path: `${SHOTS}/area-open.png` })

  // Choose another province by hand, reload: it is remembered.
  await page.select('select[aria-label="เลือกจังหวัด"]', 'กรุงเทพมหานคร')
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.body.innerText.includes('📍 กรุงเทพมหานคร'), { timeout: 20000 }).catch(() => {})
  const after = await page.evaluate(() => ({
    text: document.body.innerText.slice(0, 400), stored: localStorage.getItem('floodwatch.province') }))
  check('เลือกเองแล้วจำไว้หลังรีโหลด', after.text.includes('📍 กรุงเทพมหานคร'), JSON.stringify(after))

  const fit = await page.evaluate(() => ({ inner: innerWidth, scroll: document.documentElement.scrollWidth }))
  check('หน้าไม่กว้างเกินจอมือถือ', fit.inner === 390 && fit.scroll <= 390, JSON.stringify(fit))

  // Refused permission falls back to choosing.
  const ctx = await browser.createBrowserContext()
  const p2 = await ctx.newPage()
  await p2.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true })
  await p2.goto(BASE, { waitUntil: 'domcontentloaded' })
  await p2.waitForFunction(() => document.body.innerText.includes('ใช้ตำแหน่งของฉัน'), { timeout: 20000 }).catch(() => {})
  await p2.evaluate(() => {
    navigator.geolocation.getCurrentPosition = (ok, err) => err({ code: 1 })
    ;[...document.querySelectorAll('button')].find((x) => x.textContent.includes('ใช้ตำแหน่งของฉัน'))?.click()
  })
  await new Promise((r) => setTimeout(r, 500))
  check('ไม่อนุญาตตำแหน่ง -> บอกให้เลือกจังหวัดเอง',
    await p2.evaluate(() => document.body.innerText.includes('ไม่ได้รับอนุญาตให้ใช้ตำแหน่ง')))

  await browser.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL AREA-CARD CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
