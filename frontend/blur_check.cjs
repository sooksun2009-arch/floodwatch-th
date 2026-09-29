// Local check: tap-to-blur in the report form, and the automatic face blur,
// verified on the photo the server actually stored.
const path = require('path')
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const SHOTS = process.argv[3] || '.'
const PORTRAIT = path.join(__dirname, '..', 'backend', 'testdata', 'astronaut.jpg')
const fails = []
const check = (name, ok, extra = '') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : `\n      -> ${extra}`))
  if (!ok) fails.push(name)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Edge strength of a region of an image URL, measured in the page.
const detailIn = (page, url, box) => page.evaluate(async (u, b) => {
  const img = new Image()
  img.src = u
  await img.decode()
  const c = document.createElement('canvas')
  c.width = img.naturalWidth
  c.height = img.naturalHeight
  const ctx = c.getContext('2d')
  ctx.drawImage(img, 0, 0)
  const scale = img.naturalWidth / 512
  const [x, y, w, h] = b.map((v) => Math.round(v * scale))
  const d = ctx.getImageData(x, y, w, h).data
  let sum = 0
  let n = 0
  for (let row = 0; row < h; row++) {
    for (let col = 1; col < w; col++) {
      const i = (row * w + col) * 4
      sum += Math.abs(d[i] - d[i - 4]) + Math.abs(d[i + 1] - d[i - 3]) + Math.abs(d[i + 2] - d[i - 2])
      n++
    }
  }
  return { detail: sum / n, width: img.naturalWidth }
}, url, box)

;(async () => {
  const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const page = await browser.newPage()
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true })
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'แจ้งน้ำท่วม'), { timeout: 30000 })
  await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'แจ้งน้ำท่วม').click())
  await page.waitForSelector('#photo', { timeout: 10000 })

  const input = await page.$('#photo')
  await input.uploadFile(PORTRAIT)
  await page.waitForSelector('canvas[role="img"]', { timeout: 10000 })
  await sleep(800)
  check('เลือกรูปแล้วขึ้นพรีวิวที่แตะเบลอได้', true)
  check('มีคำแนะนำให้แตะเบลอป้ายทะเบียน', await page.evaluate(() => document.body.innerText.includes('แตะรูปเพื่อเบลอป้ายทะเบียน')))

  // Tap the name badge on the suit (lower right of the chest): stands in for
  // a licence plate -- something the automatic check would not touch.
  const BADGE = [270, 335, 70, 40] // x, y, w, h in the 512 px source
  const canvas = await page.$('canvas[role="img"]')
  // Below the fold inside the form; a tap at off-screen coordinates would land
  // on the backdrop and close the form.
  await canvas.evaluate((el) => el.scrollIntoView({ block: 'center' }))
  await sleep(300)
  const box = await canvas.boundingBox()
  const cx = box.x + box.width * ((BADGE[0] + BADGE[2] / 2) / 512)
  const cy = box.y + box.height * ((BADGE[1] + BADGE[3] / 2) / 512)
  await page.mouse.click(cx, cy)
  await sleep(300)
  check('แตะแล้วนับจุด (มีปุ่มย้อน)', await page.evaluate(() => document.body.innerText.includes('ย้อน (1)')))
  await page.screenshot({ path: `${SHOTS}/blurpad.png` })

  // Undo and redo, to prove undo works.
  await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('ย้อน'))?.click())
  await sleep(200)
  check('กดย้อนแล้วจุดหายไป', !(await page.evaluate(() => document.body.innerText.includes('ย้อน ('))))
  await canvas.evaluate((el) => el.scrollIntoView({ block: 'center' }))
  await sleep(200)
  const box2 = await canvas.boundingBox()
  await page.mouse.click(box2.x + (cx - box.x), box2.y + (cy - box.y))
  await sleep(300)
  const dlg = () => page.evaluate(() => Boolean(document.querySelector('[role="dialog"][aria-label="แจ้งน้ำท่วม"]')))
  console.log('      after re-tap: dialog', await dlg(), 'spots', await page.evaluate(() => /ย้อน \((\d+)\)/.exec(document.body.innerText)?.[1]))

  // Fill in the rest and send.
  await page.evaluate(() => {
    const byText = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.includes(t))
    byText('ปักหมุด')?.click
  })
  const hasCoords = await page.$('input[placeholder*="13."]')
  if (hasCoords) {
    await hasCoords.type('13.7460, 100.5340')
  }
  console.log('      after coords: dialog', await dlg())
  const place = await page.$('#place')
  if (place) await place.type('ถนนทดสอบเบลอ ปากซอย 3')
  await sleep(400)
  console.log('      before submit: dialog', await dlg(), await page.evaluate(() => [...document.querySelectorAll('[role=dialog] button')].map((b) => b.type + ':' + b.textContent.trim()).filter((t) => t.startsWith('submit')).join(',')))
  const uploads = []
  page.on('response', async (r) => {
    if (r.url().includes('/api/uploads') && r.request().method() === 'POST') {
      try { uploads.push(await r.json()) } catch { /* ignore */ }
    }
  })
  await page.evaluate(() => [...document.querySelectorAll('[role="dialog"] button')].find((b) => b.textContent.trim() === 'ส่งรายงาน')?.click())
  await page.waitForFunction(() => document.body.innerText.includes('ขอบคุณที่ช่วยแจ้ง') || document.body.innerText.includes('ยังขาด'), { timeout: 30000 }).catch(() => {})
  const after = await page.evaluate(() => document.body.innerText)
  if (!after.includes('ขอบคุณที่ช่วยแจ้ง')) {
    console.log('      form state:', after.slice(after.indexOf('แจ้งน้ำท่วม'), after.indexOf('แจ้งน้ำท่วม') + 400).replace(/\n/g, ' | '))
  }
  check('ส่งรายงานสำเร็จ', after.includes('ขอบคุณที่ช่วยแจ้ง'))
  check('บอกว่าเบลอใบหน้าอัตโนมัติ 1 คน', after.includes('เบลอใบหน้าในรูปให้อัตโนมัติแล้ว 1 คน'), after.slice(0, 300))
  await page.screenshot({ path: `${SHOTS}/blur-done.png` })

  const stored = uploads[0]?.url
  check('ได้ URL รูปที่บันทึก', Boolean(stored), JSON.stringify(uploads))
  if (stored) {
    const FACE = [170, 40, 120, 140]
    const origFace = await detailIn(page, `file:///${PORTRAIT.replace(/\\/g, '/')}`.replace('file:////', 'file:///'), FACE).catch(() => null)
    const savedFace = await detailIn(page, stored, FACE)
    // Inside the box the tap blurred (centred on the tap, 'medium' size),
    // not the badge's own outline: the tap need not be pixel-exact.
    const tapX = BADGE[0] + BADGE[2] / 2
    const tapY = BADGE[1] + BADGE[3] / 2
    const savedBadge = await detailIn(page, stored, [tapX - 30, tapY - 14, 60, 28])
    const savedRest = await detailIn(page, stored, [20, 300, 120, 180])
    console.log('      detail: face', savedFace.detail.toFixed(1), 'badge', savedBadge.detail.toFixed(1), 'rest', savedRest.detail.toFixed(1), 'orig face', origFace?.detail?.toFixed(1))
    check('ไฟล์ที่บันทึก: ใบหน้าเบลอ (อัตโนมัติ)', savedFace.detail < savedRest.detail * 0.5, JSON.stringify({ savedFace, savedRest }))
    check('ไฟล์ที่บันทึก: จุดที่แตะเบลอ (บนมือถือ)', savedBadge.detail < savedRest.detail * 0.5, JSON.stringify({ savedBadge, savedRest }))
  }

  await browser.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL BLUR UI CHECKS PASSED')
  process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
