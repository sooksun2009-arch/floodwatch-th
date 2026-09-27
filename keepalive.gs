/**
 * FloodWatch TH — keep-alive + เฝ้าระวัง (Google Apps Script)
 *
 * Render แพลนฟรีจะหลับเมื่อไม่มีคนเข้า แล้วตื่นช้าถึง 50 วินาที
 * ซึ่งนานเกินไปสำหรับคนที่กำลังจะตัดสินใจขับรถฝ่าน้ำท่วม
 * สคริปต์นี้ยิงเข้าไปเป็นระยะเพื่อไม่ให้หลับ
 *
 * และเนื่องจากมันรันอยู่แล้ว จึงให้มันตรวจสุขภาพระบบไปด้วย:
 * เว็บล่ม หรือข้อมูลระดับน้ำค้างเกินกำหนด จะส่งอีเมลแจ้ง
 * ("ยังตอบ 200 อยู่" ไม่ได้แปลว่าข้อมูลยังใช้ได้ — บทเรียนจากตอน deploy)
 *
 * วิธีใช้
 *   1. เปิด script.google.com → New project
 *   2. วางไฟล์นี้ทับโค้ดเดิมทั้งหมด
 *   3. เลือกฟังก์ชัน setup แล้วกด Run (ครั้งแรกจะขออนุญาต ให้กดอนุญาต)
 *   4. จบ — setup ตั้ง trigger ให้เอง ไม่ต้องไปกดในหน้า Triggers
 */

const BASE_URL = 'https://floodwatch-th.onrender.com';

/** ทุกกี่นาทีจึงยิงหนึ่งครั้ง Render หลับหลังว่าง 15 นาที จึงตั้ง 10 ให้มีระยะเผื่อ */
const PING_MINUTES = 10;

/** ถ้าข้อมูลระดับน้ำสดน้อยกว่านี้ ถือว่าการซิงก์มีปัญหา */
const MIN_FRESH_STATIONS = 300;

/** กันอีเมลถล่ม: แจ้งเตือนเรื่องเดิมซ้ำได้ไม่เกินหนึ่งครั้งในกี่ชั่วโมง */
const ALERT_COOLDOWN_HOURS = 6;

/**
 * ตั้งค่าให้ทำงานอัตโนมัติ — รันฟังก์ชันนี้ครั้งเดียวก็พอ
 * ลบ trigger เดิมของตัวเองก่อน เพื่อไม่ให้รันซ้อนกันเวลากด Run หลายรอบ
 */
function setup() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'keepAwake')
    .forEach((t) => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger('keepAwake').timeBased().everyMinutes(PING_MINUTES).create();

  const result = keepAwake();
  Logger.log('ตั้ง trigger ทุก %s นาทีแล้ว — ผลการยิงครั้งแรก: %s', PING_MINUTES, result);
  return result;
}

/** ปิดการทำงานอัตโนมัติ */
function stop() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'keepAwake')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  Logger.log('ลบ trigger แล้ว');
}

/** ฟังก์ชันที่ trigger เรียกทุกรอบ */
function keepAwake() {
  const health = fetchJson('/api/health');

  if (!health.ok) {
    alertOnce('down', 'FloodWatch TH: เว็บไม่ตอบสนอง',
              'เรียก /api/health ไม่สำเร็จ\n\n' + health.error +
              '\n\nดูสถานะได้ที่ https://dashboard.render.com');
    Logger.log('เว็บไม่ตอบ: %s', health.error);
    return 'ไม่ตอบสนอง';
  }

  // ตื่นแล้ว ทีนี้ดูว่าข้อมูลยังสดอยู่ไหม
  const stations = fetchJson('/api/stations/summary');
  if (!stations.ok) {
    Logger.log('ยิง health ผ่าน แต่ดึงสรุปสถานีไม่ได้: %s', stations.error);
    return 'ตื่นแล้ว แต่อ่านข้อมูลสถานีไม่ได้';
  }

  const s = stations.data;
  const summary = 'สถานี ' + s.total + ' จุด · สด ' + s.fresh +
                  ' · ค้าง ' + s.stale + ' · ล้นตลิ่ง ' + s.overflowing;

  if (s.fresh < MIN_FRESH_STATIONS) {
    alertOnce('stale',
              'FloodWatch TH: ข้อมูลระดับน้ำอาจค้าง',
              'เว็บตอบปกติ แต่ข้อมูลที่ยังสดมีเพียง ' + s.fresh + ' จุด ' +
              '(เกณฑ์ที่ตั้งไว้ ' + MIN_FRESH_STATIONS + ')\n\n' + summary +
              '\n\nแปลว่าการซิงก์จากต้นทางน่าจะมีปัญหา ทั้งที่หน้าเว็บยังดูปกติดี' +
              '\nตรวจ log ได้ที่ https://dashboard.render.com');
  } else {
    clearAlert('stale');
  }
  clearAlert('down');

  Logger.log(summary);
  return summary;
}

/** ดึง JSON จาก API ของเรา คืน {ok, data} หรือ {ok:false, error} */
function fetchJson(path) {
  try {
    const res = UrlFetchApp.fetch(BASE_URL + path, {
      muteHttpExceptions: true,
      // เว็บที่เพิ่งตื่นจากหลับใช้เวลาได้ถึง ~50 วินาที
      validateHttpsCertificates: true,
    });
    const code = res.getResponseCode();
    if (code !== 200) return { ok: false, error: 'HTTP ' + code };
    return { ok: true, data: JSON.parse(res.getContentText()) };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

/**
 * ส่งอีเมลแจ้งเตือน แต่ไม่ส่งซ้ำเรื่องเดิมถี่เกินไป
 * ระบบที่ส่งเมลทุก 10 นาทีจะถูกมองข้ามภายในวันเดียว
 */
function alertOnce(key, subject, body) {
  const store = PropertiesService.getScriptProperties();
  const prop = 'alerted_' + key;
  const last = Number(store.getProperty(prop) || 0);
  const now = Date.now();

  if (now - last < ALERT_COOLDOWN_HOURS * 3600 * 1000) return;

  const to = Session.getActiveUser().getEmail();
  if (to) MailApp.sendEmail(to, subject, body);
  store.setProperty(prop, String(now));
}

/** ปัญหาหายแล้ว รีเซ็ตเพื่อให้ครั้งหน้าแจ้งได้ทันที */
function clearAlert(key) {
  PropertiesService.getScriptProperties().deleteProperty('alerted_' + key);
}
