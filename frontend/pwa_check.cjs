// Installability, checked the way Chrome itself reports it.
const puppeteer = require('puppeteer-core')
const BASE = process.argv[2] || 'http://localhost:5173'
const fails = []
const check = (n, ok, x = '') => { console.log((ok ? 'PASS  ' : 'FAIL  ') + n + (ok ? '' : `\n      -> ${x}`)); if (!ok) fails.push(n) }
;(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const p = await b.newPage()
  await p.goto(BASE, { waitUntil: 'domcontentloaded' })
  await new Promise((r) => setTimeout(r, 2500))
  const files = await p.evaluate(async () => {
    const out = {}
    for (const f of ['/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/icon-maskable-512.png', '/apple-touch-icon.png']) {
      const r = await fetch(f); out[f] = `${r.status} ${r.headers.get('content-type')}`
    }
    return out
  })
  for (const [f, v] of Object.entries(files)) check(`${f} ตอบได้ (ไม่ใช่หน้าเว็บแทนไฟล์)`, v.startsWith('200') && !v.includes('text/html'), v)
  const client = await p.target().createCDPSession()
  await client.send('Page.enable')
  const { installabilityErrors } = await client.send('Page.getInstallabilityErrors')
  check('Chrome บอกว่าติดตั้งได้ (ไม่มี error)', installabilityErrors.length === 0, JSON.stringify(installabilityErrors))
  const { url, errors, data } = await client.send('Page.getAppManifest')
  const m = JSON.parse(data || '{}')
  check('อ่าน manifest ได้ ไม่มี error', !errors.length && m.display === 'standalone', JSON.stringify(errors))
  await b.close()
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL PWA CHECKS PASSED'); process.exit(fails.length ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(1) })
