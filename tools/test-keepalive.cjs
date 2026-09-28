// เทสตรรกะการเตือนใน keepalive.gs โดยจำลองสภาพแวดล้อมของ Apps Script
// รัน: node tools/test-keepalive.cjs keepalive.gs
//
// มีอยู่เพราะสคริปต์นี้รันในบัญชี Google ของผู้ใช้ ไม่มีใครเห็นตอนมันพัง
// และความผิดพลาดของมันมีสองแบบที่แย่พอกัน: เงียบตอนควรเตือน กับ สแปมจนคนเลิกอ่าน

// จำลองสภาพแวดล้อม Apps Script เท่าที่ checkPending ใช้
const props = new Map()
let pending = 0, clock = Date.now(), sent = []
global.PropertiesService = { getScriptProperties: () => ({
  getProperty: k => (props.has(k) ? props.get(k) : null),
  setProperty: (k, v) => props.set(k, v),
  deleteProperty: k => props.delete(k),
})}
global.Logger = { log: () => {} }
global.Session = { getActiveUser: () => ({ getEmail: () => 'a@b.c' }) }
global.MailApp = { sendEmail: (to, s) => sent.push(s) }
global.UrlFetchApp = { fetch: () => ({ getResponseCode: () => 200, getContentText: () => '{}' }) }
global.Utilities = { sleep: () => {} }
global.ScriptApp = {}
const realNow = Date.now
Date.now = () => clock

const src = require('fs').readFileSync(process.argv[2] || 'keepalive.gs', 'utf8')
    .replace(/^const /gm, 'var ')
eval(src)
// ให้ fetchJson คืนค่าสถิติที่เราคุม
fetchJson = p => ({ ok: true, data: { pending_moderation: pending,
  active_reports: 4, reports_last_24h: 6 } })

const fails = []
const check = (name, ok, extra='') => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (ok ? '' : '\n      -> ' + extra))
  if (!ok) fails.push(name)
}

pending = 0; sent = []; checkPending()
check('ไม่มีอะไรรออนุมัติ -> เงียบ', sent.length === 0, sent.length)

pending = 1; sent = []; checkPending()
check('มีรายการใหม่ -> เตือนทันที', sent.length === 1, sent.length)
check('หัวข้อบอกจำนวน', /รออนุมัติ 1 รายการ/.test(sent[0] || ''), sent[0])

sent = []; clock += 5 * 60000; checkPending()
check('ผ่านไป 5 นาที จำนวนเท่าเดิม -> ไม่เตือนซ้ำ', sent.length === 0, sent.length)

sent = []; pending = 3; checkPending()
check('มีเพิ่มเป็น 3 -> เตือนอีกครั้ง', sent.length === 1, sent.length)

sent = []; clock += 31 * 60000; checkPending()
check('ค้างเกิน 30 นาที -> เตือนย้ำ (ของมีอายุ)', sent.length === 1, sent.length)

sent = []; pending = 0; checkPending()
check('เคลียร์คิวหมด -> เงียบ', sent.length === 0, sent.length)
sent = []; pending = 1; checkPending()
check('มีรายการใหม่หลังเคลียร์ -> เตือนทันที ไม่ติดคูลดาวน์เดิม', sent.length === 1, sent.length)

Date.now = realNow
console.log('\n' + '='.repeat(56))
console.log(fails.length ? fails.length + ' FAILED' : 'ALL ALERT LOGIC CHECKS PASSED')
process.exit(fails.length ? 1 : 0)
