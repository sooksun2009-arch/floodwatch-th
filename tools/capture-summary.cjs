// เรนเดอร์ frontend/promo/summary.html เป็น PNG รูปเดียวไว้โพสต์
// รัน: node tools/capture-summary.cjs
//
// แยกจาก capture-promo.cjs เพราะอันนั้นถ่ายเว็บจริง อันนี้เรนเดอร์หน้าที่เราวาดเอง

const fs = require('fs')
const path = require('path')
const puppeteer = require(require.resolve('puppeteer-core', {
  paths: [path.join(__dirname, '..', 'frontend')],
}))

const CHROME = [
  String.raw`C:\Program Files\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`,
  (process.env.LOCALAPPDATA || '') + String.raw`\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
  '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]

const SRC = path.join(__dirname, '..', 'frontend', 'promo', 'summary.html')
const OUT = path.join(__dirname, '..', 'frontend', 'promo', 'สรุปฟีเจอร์.png')

;(async () => {
  const exe = process.env.CHROME_PATH || CHROME.find((p) => p && fs.existsSync(p))
  if (!exe) { console.error('ไม่พบ Chrome/Edge'); process.exit(2) }
  if (!fs.existsSync(SRC)) { console.error('ไม่พบ ' + SRC); process.exit(2) }

  const browser = await puppeteer.launch({
    executablePath: exe, headless: 'new', args: ['--no-sandbox', '--hide-scrollbars'],
  })
  const page = await browser.newPage()
  // 1080x1350 คืออัตราส่วน 4:5 ที่ Facebook แสดงเต็มโดยไม่ครอป
  await page.setViewport({ width: 1080, height: 1350, deviceScaleFactor: 2 })
  await page.goto('file://' + SRC.replace(/\\/g, '/'), { waitUntil: 'networkidle0', timeout: 60000 })
  // ฟอนต์ไทยมาจาก Google Fonts — ถ้าถ่ายก่อนโหลดเสร็จจะได้ฟอนต์ fallback
  await page.evaluate(() => document.fonts.ready)
  await new Promise((r) => setTimeout(r, 1200))

  // หน้าต้องพอดีกรอบ ไม่ล้นจนโดนตัด เช็คแทนการเปิดดูเอง
  const fit = await page.evaluate(() => ({
    scrollH: document.body.scrollHeight,
    clientH: document.body.clientHeight,
    thaiFont: getComputedStyle(document.body).fontFamily,
  }))
  if (fit.scrollH > fit.clientH + 2) {
    console.error(`เนื้อหาล้นกรอบ ${fit.scrollH - fit.clientH}px — ลดขนาดตัวอักษรหรือระยะห่าง`)
    process.exit(1)
  }

  await page.screenshot({ path: OUT })
  console.log('  ' + OUT + '  ' + Math.round(fs.statSync(OUT).size / 1024) + ' KB')
  await browser.close()
})().catch((e) => { console.error('ล้มเหลว:', e.message); process.exit(1) })
