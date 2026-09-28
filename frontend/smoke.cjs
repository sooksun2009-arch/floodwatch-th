// Frontend smoke test: loads the app in a real browser and checks that the map
// actually drew something.
//
// This exists because the backend suite cannot see this class of failure. When
// maplibre's worker failed to load, every API call still returned correct data,
// every test passed, the basemap rendered — and not one pin appeared. Only a
// real browser catches that.
//
// Usage:  node smoke.cjs [url]      (default http://localhost:5173/)
// Exits non-zero when the map is empty or the console reported an error.
const fs = require('fs')
const puppeteer = require('puppeteer-core')

const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]

const URL = process.argv[2] || 'http://localhost:5173/'
const findBrowser = () =>
  process.env.CHROME_PATH || CHROME_CANDIDATES.find((p) => p && fs.existsSync(p))

const fails = []
const check = (name, ok, extra = '') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : `\n      -> ${extra}`))
  if (!ok) fails.push(name)
}

;(async () => {
  const executablePath = findBrowser()
  if (!executablePath) {
    console.error('ไม่พบ Chrome/Edge — ตั้ง CHROME_PATH ชี้ไปที่ไฟล์เบราว์เซอร์')
    process.exit(2)
  }

  const browser = await puppeteer.launch({
    executablePath,
    headless: 'new',
    args: [
      '--no-sandbox',
      // Software WebGL: CI machines and headless sessions have no real GPU.
      '--enable-unsafe-swiftshader',
      '--use-gl=swiftshader',
      '--ignore-certificate-errors',
    ],
  })

  const page = await browser.newPage()
  await page.setViewport({ width: 1400, height: 900 })

  const errors = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('requestfailed', (r) => {
    // Tiles get aborted routinely when the camera moves; that is not a failure.
    if (/tile\.openstreetmap|ERR_ABORTED/.test(r.url() + r.failure()?.errorText)) return
    errors.push(`request failed: ${r.url().slice(0, 100)} — ${r.failure()?.errorText}`)
  })

  const target = URL + (URL.includes('?') ? '&' : '?') + '__smoke=1'
  await page.goto(target, { waitUntil: 'networkidle2', timeout: 45000 })
  // Allow the style to load and the first data fetch to land.
  await new Promise((r) => setTimeout(r, 9000))

  const state = await page.evaluate(() => {
    const canvas = document.querySelector('.maplibregl-canvas')
    const out = {
      hasCanvas: Boolean(canvas),
      banners: [...document.querySelectorAll('[class*="bg-red-950"]')].map((n) =>
        n.textContent.trim(),
      ),
      hasShell: document.body.textContent.includes('เช็คเส้นทาง'),
    }

    // Ask the map what it drew. Counting canvas pixels does not work: the
    // WebGL drawing buffer is cleared once the frame has been composited.
    const map = window.__fwMap
    if (map) {
      out.layers = {}
      for (const id of ['report-dots', 'camera-dots', 'station-dots']) {
        out.layers[id] = map.getLayer(id)
          ? map.queryRenderedFeatures({ layers: [id] }).length
          : -1
      }
    }
    return out
  })

  check('หน้าเว็บโหลดได้', state.hasShell)
  check('แผนที่สร้าง canvas', state.hasCanvas)
  check('ไม่มีแบนเนอร์ error', state.banners.length === 0, state.banners.join(' | '))
  check('ไม่มี error ใน console', errors.length === 0, errors.slice(0, 5).join('\n         '))
  check('เข้าถึงแผนที่ได้', Boolean(state.layers), 'ไม่พบ window.__fwMap')
  if (state.layers) {
    const drawn = Object.values(state.layers).reduce((a, b) => a + Math.max(b, 0), 0)
    check(
      'แผนที่วาดหมุดจริง (ไม่ใช่แผนที่เปล่า)',
      drawn > 0,
      `ทุก layer วาด 0 จุด — worker ของ maplibre อาจโหลดไม่ได้ (${JSON.stringify(state.layers)})`,
    )
    check(
      'มีครบทุกชั้นข้อมูล',
      Object.values(state.layers).every((n) => n >= 0),
      `layer ที่หายไป: ${JSON.stringify(state.layers)}`,
    )
    console.log(`      หมุดที่วาด: ${JSON.stringify(state.layers)}`)
  }

  // The safety notice is not dismissible and must be on the page from the
  // start — someone opening this during a flood has to know before anything
  // else that nobody official stands behind it and it cannot summon help.
  const notice = await page.evaluate(() => document.body.innerText)
  check('มีคำเตือนว่าไม่ใช่หน่วยงานราชการ', notice.includes('ไม่ใช่หน่วยงานราชการ'))
  check('บอกว่าไม่ใช่ช่องทางขอความช่วยเหลือ', notice.includes('ไม่ใช่ช่องทางขอความช่วยเหลือ'))
  const tels = await page.evaluate(() =>
    [...document.querySelectorAll('a[href^="tel:"]')].map((a) => a.getAttribute('href')),
  )
  check('มีปุ่มโทรสายด่วนที่กดได้จริง', tels.includes('tel:1784'), JSON.stringify(tels))

  // Placing a pin by panning the map under a crosshair, which replaced
  // tap-to-place because a tap on a phone lands on a pin or a route line.
  const clickByText = (text) =>
    page.evaluate((needle) => {
      const button = [...document.querySelectorAll('button')].find((b) =>
        b.textContent.includes(needle),
      )
      if (!button) return false
      button.click()
      return true
    }, text)

  check('มีปุ่มแจ้งน้ำท่วม', await clickByText('แจ้งน้ำท่วม'))
  await new Promise((r) => setTimeout(r, 400))
  check('ฟอร์มมีปุ่ม "เลือกจุดบนแผนที่"', await clickByText('เลือกจุดบนแผนที่'))
  await new Promise((r) => setTimeout(r, 500))

  const picking = await page.evaluate(() => ({
    prompt: document.body.innerText.includes('เลื่อนแผนที่ให้หมุดอยู่ตรง'),
    crosshair: document.querySelectorAll('.pointer-events-none svg path').length > 0,
    confirm: [...document.querySelectorAll('button')].some((b) =>
      b.textContent.includes('ยืนยันตำแหน่งนี้'),
    ),
  }))
  check('เข้าโหมดเลือกจุด: มีคำแนะนำ', picking.prompt, JSON.stringify(picking))
  check('เข้าโหมดเลือกจุด: มีหมุดกลางจอ', picking.crosshair, JSON.stringify(picking))
  check('เข้าโหมดเลือกจุด: มีปุ่มยืนยัน', picking.confirm, JSON.stringify(picking))

  if (picking.confirm) {
    await page.evaluate(() => window.__fwMap?.panBy([60, 40], { duration: 0 }))
    await new Promise((r) => setTimeout(r, 400))
    await clickByText('ยืนยันตำแหน่งนี้')
    await new Promise((r) => setTimeout(r, 600))
    const text = await page.evaluate(() => document.body.innerText)
    check('ยืนยันแล้วกลับเข้าฟอร์มพร้อมพิกัด', text.includes('ปักหมุดแล้ว'),
      text.slice(0, 200))
  }
  // Close it properly. The form's close control is an "×" with an aria-label,
  // so matching on the word alone missed it and left the dialog open over
  // everything that followed.
  const closedDialog = await page.evaluate(() => {
    const byLabel = document.querySelector('[aria-label="ปิด"]')
    if (byLabel) {
      byLabel.click()
      return true
    }
    const byText = [...document.querySelectorAll('button')].find(
      (b) => b.textContent.trim() === 'ปิด',
    )
    byText?.click()
    return Boolean(byText)
  })
  await new Promise((r) => setTimeout(r, 400))
  check('ปิดหน้าต่างแจ้งน้ำท่วมได้', closedDialog)
  check(
    'ปิดแล้วไม่มีหน้าต่างค้างทับแผนที่',
    !(await page.evaluate(() => Boolean(document.querySelector('[role="dialog"]')))),
  )

  // Filtering by the legend: picking a category shows only that one. The check
  // that matters is which pins remain on the map, not which legend row turned
  // white — those are easy to confuse and only one of them is the feature.
  const drawn = (layer) =>
    page.evaluate(
      (id) => (window.__fwMap?.getLayer(id)
        ? window.__fwMap.queryRenderedFeatures({ layers: [id] }).length
        : -1),
      layer,
    )

  const clickLegend = (label) =>
    page.evaluate((text) => {
      const b = [...document.querySelectorAll('button')].find(
        (x) => x.textContent.trim() === text,
      )
      if (!b) return false
      b.click()
      return true
    }, label)

  const settle = () => new Promise((r) => setTimeout(r, 450))
  const all = await drawn('report-dots')

  // Which levels are actually on the map right now. The old version hardcoded
  // "10-30 ซม." and "เกิน 60 ซม.", so on production -- where the live reports
  // happened to be only น้ำขัง and 10-30 ซม. -- selecting both could never add
  // up to the total and the filter was reported broken when it was not. The
  // test has to ask the map what is there, not assume the seed data.
  const LEVEL_LABELS = {
    normal: 'ปกติ', puddle: 'น้ำขัง', shallow: '10-30 ซม.',
    deep: '30-60 ซม.', severe: 'เกิน 60 ซม.', closed: 'ปิดถนน',
  }
  const present = await page.evaluate(() =>
    [...new Set(window.__fwMap
      .queryRenderedFeatures({ layers: ['report-dots'] })
      .map((f) => f.properties.level))])

  if (all >= 2 && present.length >= 2) {
    const [first, second] = present
    const firstLabel = LEVEL_LABELS[first]
    const secondLabel = LEVEL_LABELS[second]

    check(`กดคำอธิบายสี "${firstLabel}" ได้`, await clickLegend(firstLabel))
    await settle()
    const onlyFirst = await drawn('report-dots')
    check('เลือกหนึ่งชนิด -> เห็นเฉพาะชนิดนั้น', onlyFirst > 0 && onlyFirst < all,
      `ทั้งหมด ${all} -> เลือกแล้ว ${onlyFirst}`)

    check('บอกว่ากำลังกรองอยู่', await page.evaluate(
      () => document.body.innerText.includes('แสดงเฉพาะ')))

    await clickLegend(secondLabel)
    await settle()
    const both = await drawn('report-dots')
    check('เลือกเพิ่มได้ -> เห็นมากขึ้น', both > onlyFirst && both <= all,
      `หนึ่งชนิด ${onlyFirst} -> สองชนิด ${both} (ทั้งหมด ${all})`)

    await clickLegend(firstLabel)
    await settle()
    check('กดซ้ำเพื่อเอาออกจากที่เลือก', (await drawn('report-dots')) < both,
      `${await drawn('report-dots')} vs ${both}`)

    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) =>
        x.textContent.includes('กดเพื่อแสดงทั้งหมด'),
      )
      b?.click()
    })
    await settle()
    check('ล้างตัวกรอง -> กลับมาครบ', (await drawn('report-dots')) === all,
      `${await drawn('report-dots')} vs ${all}`)
  } else {
    console.log('      (ข้ามเทสตัวกรอง: มีหมุดบนจอ ' + all + ' จุด '
      + 'ใน ' + present.length + ' ระดับ — ต้องการอย่างน้อย 2 จุด 2 ระดับ. '
      + 'ข้าม ไม่ใช่ผ่าน)')
  }

  // The share button, both ways it can work. On a Thai phone the native sheet
  // is how this reaches LINE; on a desktop there is no sheet and the clipboard
  // is the whole feature.
  await page.evaluate(() => {
    window.__shared = null
    window.__copied = null
    navigator.share = (data) => {
      window.__shared = data
      return Promise.resolve()
    }
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: (t) => { window.__copied = t; return Promise.resolve() } },
    })
  })

  const pressShare = () =>
    page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) =>
        x.textContent.includes('แชร์'),
      )
      if (!b) return false
      b.click()
      return true
    })

  check('มีปุ่มแชร์บนหัวเว็บ', await pressShare())
  await new Promise((r) => setTimeout(r, 300))
  const shared = await page.evaluate(() => window.__shared)
  check('กดแล้วเรียกแผงแชร์ของเครื่อง', Boolean(shared), JSON.stringify(shared))
  if (shared) {
    check(
      'แชร์หน้าแรกของแอป ไม่ใช่ URL ที่เปิดอยู่',
      shared.url === (await page.evaluate(() => window.location.origin)),
      `${shared.url} vs origin`,
    )
    check('ข้อความแชร์บอกว่าแอปทำอะไร',
      /น้ำท่วม/.test(shared.title + shared.text), JSON.stringify(shared))
  }

  // No native sheet: the link has to end up on the clipboard instead.
  await page.evaluate(() => {
    // Assigning undefined rather than delete: delete removes only the own
    // property and uncovers the browser's native share, which is not what a
    // desktop without one looks like.
    Object.defineProperty(navigator, 'share', { configurable: true, value: undefined })
    window.__copied = null
  })
  await pressShare()
  await new Promise((r) => setTimeout(r, 300))
  const copied = await page.evaluate(() => window.__copied)
  check('ไม่มีแผงแชร์ -> คัดลอกลิงก์แทน', Boolean(copied && copied.includes('http')), copied)
  const told = await page.evaluate(() => document.body.innerText.includes('คัดลอกลิงก์แล้ว'))
  check('และบอกผู้ใช้ว่าคัดลอกแล้ว', told)

  // Floating controls must not sit on top of one another. This app keeps
  // growing corner buttons — radar, report, chat, zoom, locate — and two of
  // them landed on each other twice before anyone noticed, because each was
  // correct in isolation.
  const overlaps = await page.evaluate(() => {
    const seen = new Map()
    const add = (label, el) => {
      if (!el) return
      const r = el.getBoundingClientRect()
      if (r.width < 8 || r.height < 8) return
      if (getComputedStyle(el).visibility === 'hidden') return
      seen.set(label + ':' + Math.round(r.x) + ',' + Math.round(r.y), { label, r })
    }
    document
      .querySelectorAll('.maplibregl-ctrl button, button, a[href^="tel:"]')
      .forEach((el) => {
        const style = getComputedStyle(el)
        if (style.position === 'static') return
        add((el.textContent || el.className || 'ปุ่ม').trim().slice(0, 18), el)
      })
    const items = [...seen.values()]
    const hits = []
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i].r
        const b = items[j].r
        const dx = Math.min(a.right, b.right) - Math.max(a.left, b.left)
        const dy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        if (dx > 4 && dy > 4) hits.push(`${items[i].label} ทับ ${items[j].label}`)
      }
    }
    return hits
  })
  check('ปุ่มลอยบนแผนที่ไม่ทับกัน', overlaps.length === 0, overlaps.join(' · '))

  // Turn on every optional layer at once and measure the boxes they add. The
  // radar caption, the satellite caption and the legend each looked right
  // alone and collided in pairs on the live site -- twice, reported by the
  // user rather than caught here.
  const captions = await page.evaluate(async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms))
    for (const word of ['เรดาร์ฝน', 'ดาวเทียม']) {
      const b = [...document.querySelectorAll('button')]
        .find((x) => x.textContent.includes(word) && x.getAttribute('aria-pressed') === 'false')
      b?.click()
      await wait(700)
    }
    const boxes = [...document.querySelectorAll('.backdrop-blur')]
      .map((el) => ({
        label: el.textContent.replace(/\s+/g, ' ').trim().slice(0, 22),
        r: el.getBoundingClientRect(),
      }))
      .filter((b) => b.r.width > 20 && b.r.height > 10)
    const hits = []
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i].r, c = boxes[j].r
        if (boxes[i].label && a.contains) continue
        const dx = Math.min(a.right, c.right) - Math.max(a.left, c.left)
        const dy = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top)
        // Skip nesting: a caption inside its own stack is not a collision.
        const nested = (a.left <= c.left && a.right >= c.right &&
                        a.top <= c.top && a.bottom >= c.bottom) ||
                       (c.left <= a.left && c.right >= a.right &&
                        c.top <= a.top && c.bottom >= a.bottom)
        if (!nested && dx > 4 && dy > 4) {
          hits.push(`"${boxes[i].label}" ทับ "${boxes[j].label}"`)
        }
      }
    }
    return { count: boxes.length, hits }
  })
  check('เปิดทุกเลเยอร์พร้อมกัน -> กล่องคำอธิบายไม่ทับกัน',
        captions.hits.length === 0, captions.hits.join(' · '))

  // The OpenStreetMap credit has to stay readable. Using the map is
  // conditional on showing it, and it sits in the same corner the buttons keep
  // moving into: "แจ้งน้ำท่วม" covered 96 of its 161 pixels on a phone and the
  // chat button covered 54 on a wide screen, both shipped. Checked at two
  // widths because the two screens put a different button in that corner.
  const coverage = async () => page.evaluate(() => {
    const attr = document.querySelector('.maplibregl-ctrl-attrib')
    if (!attr) return { missing: true }
    const a = attr.getBoundingClientRect()
    const hits = []
    for (const el of document.querySelectorAll('button, a')) {
      if (attr.contains(el)) continue
      const r = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      if (r.width < 8 || style.visibility === 'hidden') continue
      const dx = Math.min(a.right, r.right) - Math.max(a.left, r.left)
      const dy = Math.min(a.bottom, r.bottom) - Math.max(a.top, r.top)
      if (dx > 1 && dy > 1) {
        const label = (el.getAttribute('aria-label') || el.textContent || '').trim()
        hits.push(`${label.slice(0, 18)} บัง ${Math.round(dx)} จาก ${Math.round(a.width)} px`)
      }
    }
    return { hits, onscreen: a.left >= -1 && a.top >= -1 && a.bottom <= innerHeight + 1 }
  })

  const attrWide = await coverage()
  check('เครดิต OpenStreetMap ไม่ถูกปุ่มบัง (จอกว้าง)',
        !attrWide.missing && attrWide.hits.length === 0,
        attrWide.missing ? 'ไม่พบเครดิตบนแผนที่' : attrWide.hits.join(' · '))
  check('และอยู่ในกรอบหน้าจอ', attrWide.onscreen === true, JSON.stringify(attrWide))

  await page.setViewport({ width: 430, height: 932 })
  await new Promise((r) => setTimeout(r, 1500))
  const attrPhone = await coverage()
  check('เครดิต OpenStreetMap ไม่ถูกปุ่มบัง (บนมือถือ)',
        !attrPhone.missing && attrPhone.hits.length === 0,
        attrPhone.missing ? 'ไม่พบเครดิตบนแผนที่' : attrPhone.hits.join(' · '))
  await page.setViewport({ width: 1400, height: 900 })
  await new Promise((r) => setTimeout(r, 1500))

  // Rain features are off until a key is configured, and the button that
  // controls them must be absent rather than present and broken.
  const rain = await page.evaluate(async () => {
    const status = await fetch('/api/rain/status').then((r) => r.json()).catch(() => null)
    return {
      enabled: Boolean(status && status.enabled),
      button: [...document.querySelectorAll('button')].some((b) =>
        b.textContent.includes('เรดาร์ฝน'),
      ),
      layer: Boolean(window.__fwMap?.getLayer?.('radar-layer')),
    }
  })
  check('ถาม /api/rain/status ได้', rain.enabled !== undefined, JSON.stringify(rain))
  check(
    rain.enabled ? 'เปิดเรดาร์ได้ -> มีปุ่มให้กด' : 'ยังไม่ตั้งคีย์ -> ไม่โชว์ปุ่มเรดาร์',
    rain.button === rain.enabled,
    JSON.stringify(rain),
  )
  check('ชั้นเรดาร์ถูกสร้างไว้รอ (สลับด้วยการซ่อน ไม่ใช่โหลดใหม่)', rain.layer,
    JSON.stringify(rain))

  // Click a flood pin and use the buttons on it. These moved onto the popup
  // because the map is how most people find a pin, and the only way to say
  // "the water has gone" used to be buried in the route results panel.
  if (state.layers && state.layers['report-dots'] > 0) {
    const opened = await page.evaluate(() => {
      const map = window.__fwMap
      const found = map.queryRenderedFeatures({ layers: ['report-dots'] })
      // Prefer one with a photo: a tall portrait picture is what used to push
      // the buttons under it off the bottom of the screen.
      const feature = found.find((f) => f.properties.photo) || found[0]
      if (!feature) return false
      const point = map.project(feature.geometry.coordinates)
      map.fire('click', {
        lngLat: map.unproject(point), point, features: [feature],
        originalEvent: new MouseEvent('click'),
      })
      return true
    })
    check('กดหมุดน้ำท่วมแล้วเปิด popup ได้', opened)

    if (opened) {
      const labels = await page.evaluate(() =>
        [...document.querySelectorAll('.maplibregl-popup-content button')]
          .map((b) => b.textContent.trim()),
      )
      check('popup มีปุ่ม "น้ำลดแล้ว"', labels.includes('น้ำลดแล้ว'), JSON.stringify(labels))
      check('popup มีปุ่ม "ยังท่วมอยู่"', labels.includes('ยังท่วมอยู่'), JSON.stringify(labels))

      const before = await page.evaluate(
        () => document.querySelector('.maplibregl-popup-content').textContent,
      )
      await page.evaluate(() => {
        const button = [...document.querySelectorAll('.maplibregl-popup-content button')]
          .find((b) => b.textContent.trim() === 'น้ำลดแล้ว')
        button?.click()
      })
      let after = before
      for (let i = 0; i < 20; i++) {
        after = await page.evaluate(
          () => document.querySelector('.maplibregl-popup-content')?.textContent || '',
        )
        if (after.includes('ขอบคุณ') || after.includes('ไม่สำเร็จ')) break
        await new Promise((r) => setTimeout(r, 400))
      }
      check('กด "น้ำลดแล้ว" แล้วส่งสำเร็จ', after.includes('ขอบคุณ'), after.slice(0, 180))
      check(
        'ตัวเลขแย้งเพิ่มขึ้นจริง หลังกด',
        /แย้ง\s*[1-9]/.test(after),
        `ก่อน: ${before.slice(0, 90)}
         หลัง: ${after.slice(0, 90)}`,
      )
      // The buttons are useless if a photo pushed them past the bottom edge.
      const layout = await page.evaluate(() => {
        const popup = document.querySelector('.maplibregl-popup-content')
        const image = popup?.querySelector('img')
        const button = [...popup.querySelectorAll('button')].find((b) =>
          b.textContent.includes('น้ำลดแล้ว'),
        )
        const rect = button?.getBoundingClientRect()
        return {
          photoHeight: image ? Math.round(image.getBoundingClientRect().height) : null,
          buttonBottom: rect ? Math.round(rect.bottom) : null,
          viewport: window.innerHeight,
        }
      })
      if (layout.photoHeight !== null) {
        check(
          'รูปในป๊อปอัปไม่สูงเกินเพดาน',
          layout.photoHeight <= 200,
          `สูง ${layout.photoHeight}px`,
        )
      }
      check(
        'ปุ่มโหวตอยู่ในจอ ไม่ถูกรูปดันตกขอบ',
        layout.buttonBottom !== null && layout.buttonBottom <= layout.viewport,
        JSON.stringify(layout),
      )
      console.log(`      popup หลังกด: ${after.replace(/\s+/g, ' ').slice(0, 120)}`)
      console.log(`      รูปสูง ${layout.photoHeight}px · ปุ่มอยู่ที่ ${layout.buttonBottom}/${layout.viewport}px`)
    }
  }

  // Click a gauge and wait for its trend to arrive. The popup opens with a
  // placeholder and fills in from a second request, so "the popup appeared" is
  // not the same as "the trend works" — a broken fetch leaves the placeholder
  // sitting there forever and everything else still passes.
  if (state.layers && state.layers['station-dots'] > 0) {
    const clicked = await page.evaluate(() => {
      const map = window.__fwMap
      // Close whatever is already open first. The report popup from the test
      // above was still on screen, so the reads below picked up its content
      // instead of the gauge's and reported the gauge broken for a week while
      // it worked perfectly in production.
      document.querySelectorAll('.maplibregl-popup-close-button')
        .forEach((b) => b.click())
      const feature = map.queryRenderedFeatures({ layers: ['station-dots'] })[0]
      if (!feature) return null
      const point = map.project(feature.geometry.coordinates)
      map.fire('click', {
        lngLat: map.unproject(point),
        point,
        features: [feature],
        originalEvent: new MouseEvent('click'),
      })
      return feature.properties.name || 'สถานี'
    })
    check('กดหมุดสถานีแล้วเปิด popup ได้', Boolean(clicked), 'ไม่พบหมุดสถานีให้กด')

    if (clicked) {
      // Wait for the popup that belongs to THIS gauge, not for any popup.
      // Reading whichever one happens to be first in the DOM is how the
      // previous version read a leftover report popup and, when the timing
      // shifted, an empty one.
      let text = ''
      for (let i = 0; i < 40; i++) {
        text = await page.evaluate((name) => {
          const mine = [...document.querySelectorAll('.maplibregl-popup-content')]
            .find((el) => el.textContent.includes(name.slice(0, 8)))
          return mine ? mine.textContent : ''
        }, clicked)
        if (text && !text.includes('กำลังดูแนวโน้ม')) break
        await new Promise((r) => setTimeout(r, 500))
      }
      check('popup แสดงชื่อสถานี', text.includes(clicked.slice(0, 8)), text.slice(0, 160))
      check(
        'แนวโน้มโหลดเสร็จ ไม่ค้างที่ "กำลังดูแนวโน้ม…"',
        text && !text.includes('กำลังดูแนวโน้ม'),
        text.slice(0, 200) || '(popup ว่าง)',
      )
      // "ไม่สำเร็จ" is deliberately NOT accepted here. A failed fetch is a
      // legitimate thing for the page to say to a user, but in a smoke test it
      // means the endpoint is missing or broken, which is the whole point of
      // running this.
      check(
        'ดึงแนวโน้มสำเร็จ (ไม่ใช่ขึ้นว่าดึงไม่สำเร็จ)',
        !/ไม่สำเร็จ/.test(text),
        text.slice(0, 200),
      )
      const settled = /กำลังขึ้น|กำลังลง|ทรงตัว/.test(text) || /ไม่มีข้อมูล|ยังไม่/.test(text)
      check('บอกแนวโน้ม หรือบอกตรง ๆ ว่าไม่มีข้อมูล', settled, text.slice(0, 200))
      const svgs = await page.evaluate(
        () => document.querySelectorAll('.maplibregl-popup-content svg polyline').length,
      )
      console.log(`      ข้อความใน popup: ${text.replace(/\s+/g, ' ').slice(0, 110)}`)
      console.log(`      เส้นกราฟที่วาด: ${svgs}`)
    }
  }

  await page.screenshot({ path: 'smoke.png' })
  await browser.close()

  console.log('')
  console.log('='.repeat(60))
  if (fails.length) {
    console.log(`${fails.length} FAILED: ${fails.join(', ')}  (ดูภาพที่ smoke.png)`)
    process.exit(1)
  }
  console.log('ALL FRONTEND SMOKE CHECKS PASSED')
})().catch((e) => {
  console.error('smoke test ล้มเหลว:', e.message)
  process.exit(1)
})
