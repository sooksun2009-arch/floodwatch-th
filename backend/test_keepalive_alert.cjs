// When keepalive.gs should wake the owner about gauge data, and when it must
// not. The alert used to fire on "fewer than 300 fresh stations" and assert
// that our sync had broken — which at 4am was a lie: the national source goes
// quiet overnight while our sync runs every 15 minutes throughout.
//
// Apps Script has no test runner, so the pure decision functions are loaded
// out of the .gs file and exercised here.
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const source = fs.readFileSync(path.join(__dirname, '..', 'keepalive.gs'), 'utf8')
const context = { Date, isNaN, Object, JSON, Math, console }
vm.createContext(context)
vm.runInContext(source, context)
const { staleAlertReason, ageInHours, SOURCE_QUIET_ALERT_HOURS } = context

const fails = []
const check = (name, ok, extra = '') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : `\n      -> ${extra}`))
  if (!ok) fails.push(name)
}
const hoursAgo = (h) => new Date(Date.now() - h * 3600000).toISOString()

const okSources = { thaiwater: { ok: true, error: null } }

// The 4am case that started this: every reading old, sync perfectly healthy.
check('ต้นทางเงียบข้ามคืน (8 ชม.) ซิงก์ปกติ -> ไม่ปลุก',
  staleAlertReason({ total: 807, fresh: 0, stale: 807, sources: okSources,
                     newest_measured_at: hoursAgo(8) }) === null)

check('ต้นทางเงียบนานผิดปกติ (20 ชม.) -> เตือน',
  /ไม่มีข้อมูลใหม่/.test(staleAlertReason({ total: 807, fresh: 0, sources: okSources,
                                            newest_measured_at: hoursAgo(20) }) || ''))

const failing = (streak) => ({
  total: 807, fresh: 700, consecutive_failures: streak,
  sources: { thaiwater: { ok: false, error: 'ต้นทางตอบ HTTP 429' } },
  newest_measured_at: hoursAgo(1), last_success_at: hoursAgo(2) })

// The 16:20 case on 2026-10-03: one 429, then the retry thirty minutes later
// simply worked. The alert fired on the first failure and woke the owner for
// something that had already mended itself.
check('ล้มเหลวรอบเดียว (429 ชั่วคราว) -> ไม่ปลุก', staleAlertReason(failing(1)) === null)
check('ล้มเหลว 2 รอบติด -> ยังไม่ปลุก', staleAlertReason(failing(2)) === null)
check('ล้มเหลว 3 รอบติด -> เตือน',
  /ติดกัน 3 รอบ/.test(staleAlertReason(failing(3)) || ''))
check('บอกสาเหตุและเวลาที่ซิงก์สำเร็จล่าสุดมาด้วย',
  /HTTP 429/.test(staleAlertReason(failing(5)) || '')
  && /ซิงก์สำเร็จล่าสุด/.test(staleAlertReason(failing(5)) || ''))
check('API เก่าที่ไม่ส่งจำนวนรอบ -> ไม่ปลุกมั่ว',
  staleAlertReason({ total: 807, sources: { thaiwater: { ok: false, error: 'x' } },
                     newest_measured_at: hoursAgo(1) }) === null)

check('ทุกอย่างปกติ -> ไม่ปลุก',
  staleAlertReason({ total: 807, fresh: 791, sources: okSources,
                     newest_measured_at: hoursAgo(0.5) }) === null)

check('ไม่มีสถานีเลย -> เตือน (ฐานข้อมูลว่าง)',
  /ไม่มีสถานีในระบบ/.test(staleAlertReason({ total: 0, fresh: 0, sources: {},
                                             newest_measured_at: null }) || ''))

check('API เก่าที่ยังไม่ส่งเวลาที่วัด -> ไม่ปลุกมั่ว',
  staleAlertReason({ total: 807, fresh: 0, sources: okSources }) === null)

// The trap: a UTC timestamp without a Z is read as local time by Date, which
// in Bangkok makes a reading look seven hours younger than it is — enough to
// hide a genuinely dead feed.
const naive = new Date(Date.now() - 20 * 3600000).toISOString().replace('Z', '')
const naiveAge = ageInHours(naive)
check('เวลาที่ไม่มี Z ต่อท้าย ยังคิดเป็น UTC (ไม่คลาดไป 7 ชม.)',
  naiveAge > 19.5 && naiveAge < 20.5, naiveAge)
check('เวลาอ่านไม่ได้ -> null ไม่ใช่ 0', ageInHours('ไม่ใช่เวลา') === null
  && ageInHours(null) === null && ageInHours('') === null)

// Tested through behaviour, not by reading the constant: a top-level `const`
// in the .gs file does not attach to the VM's context object the way a
// function declaration does.
const quietAt = (h) => staleAlertReason({ total: 807, fresh: 0, sources: okSources,
                                          newest_measured_at: hoursAgo(h) })
check('เงียบ 12 ชม. (ยังอยู่ในช่วงข้ามคืน) -> ไม่ปลุก', quietAt(12) === null, quietAt(12))
check('เงียบ 16 ชม. (นานกว่าคืนหนึ่ง) -> เตือน', quietAt(16) !== null)

console.log()
console.log('='.repeat(60))
console.log(fails.length ? `${fails.length} FAILED` : 'ALL KEEPALIVE-ALERT CHECKS PASSED')
process.exit(fails.length ? 1 : 0)
