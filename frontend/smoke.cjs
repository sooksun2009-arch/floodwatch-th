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

  // Click a gauge and wait for its trend to arrive. The popup opens with a
  // placeholder and fills in from a second request, so "the popup appeared" is
  // not the same as "the trend works" — a broken fetch leaves the placeholder
  // sitting there forever and everything else still passes.
  if (state.layers && state.layers['station-dots'] > 0) {
    const clicked = await page.evaluate(() => {
      const map = window.__fwMap
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
      let text = ''
      for (let i = 0; i < 40; i++) {
        text = await page.evaluate(
          () => document.querySelector('.maplibregl-popup-content')?.textContent || '',
        )
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
