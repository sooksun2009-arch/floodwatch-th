// ถ่ายภาพหน้าจอจากเว็บจริงไว้ใช้โพสต์ — ภาพจริง ไม่ใช่ภาพจำลอง
// รัน: node tools/capture-promo.cjs [url] [โฟลเดอร์ปลายทาง]
//
// ถ่ายจาก production เพราะสิ่งที่เอาไปโฆษณาต้องเป็นสิ่งที่คนกดเข้าไปแล้วเจอจริง

const fs = require('fs')
const path = require('path')
// puppeteer-core is declared by the frontend, which is where the browser tests
// live; resolve it from there rather than adding a second copy for this script.
const puppeteer = require(require.resolve('puppeteer-core', {
  paths: [path.join(__dirname, '..', 'frontend')],
}))

// Reuses the browser the smoke test already found. Set CHROME_PATH if it is
// somewhere else; hardcoding Windows paths here got them mangled once already.
const CHROME = [
  String.raw`C:\Program Files\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`,
  (process.env.LOCALAPPDATA || '') + String.raw`\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
  '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]
const SITE = process.argv[2] || 'https://floodwatch-th.onrender.com'
const OUT = process.argv[3] || 'promo'
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
  const exe = process.env.CHROME_PATH || CHROME.find((p) => p && fs.existsSync(p))
  if (!exe) { console.error('ไม่พบ Chrome/Edge'); process.exit(2) }
  fs.mkdirSync(OUT, { recursive: true })

  const browser = await puppeteer.launch({
    executablePath: exe, headless: 'new',
    args: ['--no-sandbox', '--hide-scrollbars'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1200, height: 630, deviceScaleFactor: 2 })
  await page.goto(SITE + '/?__smoke=1', { waitUntil: 'networkidle2', timeout: 120000 })
  await wait(6000)

  // Centre on Bangkok and its surroundings, where most of the reports are.
  await page.evaluate(() => {
    window.__fwMap?.jumpTo({ center: [100.58, 13.76], zoom: 9.4 })
  })
  await wait(4000)
  const shot = async (name, opts = {}) => {
    const file = path.join(OUT, name)
    await page.screenshot({ path: file, ...opts })
    console.log('  ' + file + '  ' + Math.round(fs.statSync(file).size / 1024) + ' KB')
  }
  await shot('1-แผนที่.png')

  // Same view with the legend folded away. Expanded, it explains the colours,
  // which is what a first-time visitor needs; folded, the pins are the picture,
  // which is what a post needs. Shoot both and let the poster choose.
  const folded = await page.evaluate(() => {
    const b = document.querySelector('[aria-label="ย่อคำอธิบายสัญลักษณ์"]')
    b?.click()
    return Boolean(b)
  })
  if (folded) { await wait(1200); await shot('1b-แผนที่-ไม่มีคำอธิบาย.png') }
  else console.log('  (ย่อคำอธิบายไม่ได้ ข้ามภาพ 1b)')
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      x.textContent.trim() === 'สัญลักษณ์')
    b?.click()
  })
  await wait(1000)

  // Radar on, so the post can show what the rain layer looks like.
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      x.textContent.includes('เรดาร์ฝน'))
    b?.click()
  })
  await wait(6000)
  await shot('2-เรดาร์ฝน.png')
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      x.textContent.includes('เรดาร์ฝน'))
    b?.click()
  })
  await wait(1500)

  // The thing the app is for: a route, checked.
  await page.setViewport({ width: 1200, height: 900, deviceScaleFactor: 2 })
  await wait(1500)
  const typed = await page.evaluate(async () => {
    const set = (el, value) => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set
      setter.call(el, value)
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    const inputs = [...document.querySelectorAll('input')]
    const from = inputs.find((i) => (i.placeholder || '').includes('บางนา'))
    const to = inputs.find((i) => (i.placeholder || '').includes('ลาดพร้าว'))
    if (!from || !to) return false
    set(from, 'บางนา'); set(to, 'รามคำแหง')
    return true
  })
  if (typed) {
    await wait(1200)
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) =>
        x.textContent.includes('เช็คเส้นทางนี้'))
      b?.click()
    })
    await wait(12000)
    await shot('3-เช็คเส้นทาง.png')
  } else {
    console.log('  (กรอกช่องค้นหาไม่ได้ ข้ามภาพเส้นทาง)')
  }

  // Phone view — most people will open this on a phone.
  await page.setViewport({ width: 430, height: 932, deviceScaleFactor: 3 })
  await page.reload({ waitUntil: 'networkidle2', timeout: 120000 })
  await wait(7000)
  await shot('4-บนมือถือ.png')

  await browser.close()
})().catch((e) => { console.error('ล้มเหลว:', e.message); process.exit(1) })
