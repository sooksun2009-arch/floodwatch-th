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

/**
 * ขึ้นบรรทัดใหม่ เขียนเป็นรหัสอักขระแทนการใช้ escape
 * เพราะไฟล์นี้ถูกแก้ด้วยสคริปต์บ่อย และ escape เพี้ยนได้ง่ายระหว่างทาง
 */
const NEWLINE = String.fromCharCode(10);

/**
 * ทุกกี่นาทีจึงยิงหนึ่งครั้ง
 *
 * Render หลับหลังว่าง 15 นาที ลำพังการกันหลับใช้ 10 ก็พอ แต่รอบนี้ยังเป็น
 * จังหวะเดียวที่ตรวจรายงานรออนุมัติด้วย และ 10 นาทีนานเกินไปสำหรับของที่มีอายุ
 * คนแจ้งว่าน้ำท่วมแล้วยืนรออยู่ตรงนั้น ไม่ได้รอให้เราครบรอบ
 *
 * 5 นาทีคือ 288 รอบต่อวัน รอบละไม่กี่วินาที ยังห่างจากโควตาเวลารันของ
 * Apps Script (ราว 90 นาทีต่อวันสำหรับบัญชีทั่วไป) อยู่มาก
 */
const PING_MINUTES = 5;

/**
 * โทเคนสำหรับส่งข้อมูล กทม. เข้าเว็บ ต้องตรงกับ INGEST_TOKEN ที่ตั้งไว้ใน Render
 * เว้นว่างไว้ = ไม่ทำหน้าที่รีเลย์ ยิงกันหลับอย่างเดียว
 */
const INGEST_TOKEN = '';

/**
 * หน้าเว็บของสำนักการระบายน้ำ กทม.
 *
 * วัดแล้วเมื่อ 2026-09-28: เครื่องในไทยต่อได้ใน 0.18 วินาที, Render ที่สิงคโปร์
 * โดนตัดสาย (connection reset), และ Google Apps Script ขึ้น "Address unavailable"
 * แปลว่าเว็บเขาตัดทราฟฟิกจากเครือข่ายศูนย์ข้อมูล ไม่ใช่ตัดตามประเทศ
 *
 * รีเลย์ตัวนี้จึงใช้ไม่ได้ตราบใดที่ยังรันบนเครื่องของ Google — เก็บไว้เพราะ
 * ฝั่งรับข้อมูลพร้อมแล้ว และย้ายไปรันบนเครื่องที่ต่อได้เมื่อไหร่ก็ใช้ได้ทันที
 */
const BMA_BASE = 'https://weather.bangkok.go.th/water';

/**
 * ดึงหน้ารายละเอียดกี่สถานีต่อรอบ เอาไว้เก็บพิกัด
 *
 * พิกัดเก็บครั้งเดียวใช้ตลอด แต่ตอนเริ่มต้นมีราว 300 สถานีที่ยังไม่มี
 * รอบละ 5 แปลว่าใช้เวลาสิบชั่วโมงกว่าแผนที่จะเต็ม ซึ่งนานเกินไปสำหรับ
 * ของที่ควรใช้ได้ตั้งแต่วันนี้ — 25 ทำให้เหลือราวสองชั่วโมง
 *
 * ยังถือว่าเบามือ: 25 ครั้งต่อสิบนาที คือ 2.5 ครั้งต่อนาที บนเว็บของ
 * หน่วยงานอื่น และเว้นจังหวะระหว่างคำขอด้วย COORDS_DELAY_MS
 */
const COORDS_PER_RUN = 25;

/** เว้นจังหวะระหว่างการดึงแต่ละหน้า (มิลลิวินาที) */
const COORDS_DELAY_MS = 600;

/** ถ้าข้อมูลระดับน้ำสดน้อยกว่านี้ ถือว่าการซิงก์มีปัญหา */
const MIN_FRESH_STATIONS = 300;

/**
 * ต้นทาง (คลังข้อมูลน้ำแห่งชาติ) เงียบข้ามคืนเป็นปกติ วัดเมื่อ 2026-09-30:
 * ตี 4 ทุกสถานีอายุเกิน 6 ชม. พร้อมกัน พอ 9 โมงเช้ามี 474 จาก 806 สถานี
 * รายงานภายในชั่วโมงเดียว เกินค่านี้คือเงียบนานกว่าคืนหนึ่ง ซึ่งผิดปกติจริง
 */
const SOURCE_QUIET_ALERT_HOURS = 14;

/** กันอีเมลถล่ม: แจ้งเตือนเรื่องเดิมซ้ำได้ไม่เกินหนึ่งครั้งในกี่ชั่วโมง */
const ALERT_COOLDOWN_HOURS = 6;

/**
 * รายงานที่รออนุมัติเตือนถี่กว่านั้น เพราะมันมีอายุ
 * คนแจ้งว่าน้ำท่วมตอนตีสอง ถ้ากว่าจะรู้ตอนเช้า ข้อมูลก็หมดประโยชน์ไปแล้ว
 * และเตือนซ้ำเฉพาะเมื่อมีรายการใหม่เพิ่ม ไม่ใช่ย้ำเรื่องเดิมทุกรอบ
 */
const PENDING_REMINDER_MINUTES = 30;

/**
 * แจ้งเตือนผ่าน Telegram ด้วย (ไม่บังคับ)
 * อีเมลบนมือถือมักเงียบ ส่วน Telegram เด้งเสียงเหมือนแชท
 * วิธีตั้ง: ทักหา @BotFather ใน Telegram -> /newbot -> ได้โทเคนมาใส่ช่องล่าง
 *          แล้วทักหาบอทตัวเองหนึ่งข้อความ -> รัน telegramChatId() เพื่อหาเลขห้อง
 * เว้นว่างไว้ = ใช้อีเมลอย่างเดียว
 */
const TELEGRAM_BOT_TOKEN = '';
const TELEGRAM_CHAT_ID = '';

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
  Logger.log('ตั้ง trigger ทุก %s นาทีแล้ว — ผลการยิงครั้งแรก: %s', String(PING_MINUTES), result);
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

  // เตือนเฉพาะเรื่องที่ทำอะไรได้
  //
  // เดิมเตือนเมื่อ "สถานีสด" ต่ำกว่าเกณฑ์ แล้วสรุปเองว่า "การซิงก์น่าจะมีปัญหา"
  // ซึ่งไม่จริง คลังข้อมูลน้ำแห่งชาติเงียบตอนกลางคืน พอถึงตี 4 ทุกสถานีก็อายุ
  // เกิน 6 ชม. พร้อมกันหมด ทั้งที่ระบบเราซิงก์ทุก 15 นาทีอยู่ตลอด (วัดแล้ว)
  // เตือนเรื่องที่เจ้าของแก้ไม่ได้ กลางดึก คือวิธีทำให้การเตือนครั้งที่สำคัญจริง
  // ถูกมองข้าม
  //
  // สองกรณีที่ยังเตือน: ซิงก์ของเราล้มเหลวจริง และต้นทางเงียบนานกว่าคืนหนึ่ง
  const why = staleAlertReason(s);
  if (why) {
    alertOnce('stale', 'FloodWatch TH: ข้อมูลระดับน้ำมีปัญหา',
              why + '\n\n' + summary +
              '\n\nข้อมูลล่าสุดที่วัดได้: ' + (s.newest_measured_at || 'ไม่ทราบ') +
              '\nซิงก์ล่าสุดของเรา: ' + (s.last_synced_at || 'ไม่ทราบ') +
              '\n\nตรวจ log ได้ที่ https://dashboard.render.com');
  } else {
    clearAlert('stale');
  }
  clearAlert('down');

  Logger.log(summary);

  // รายงานที่รออนุมัติ — เรื่องเดียวที่ต้องให้คนกดอะไรสักอย่าง
  try {
    checkPending();
    checkNewReports();
  } catch (e) {
    Logger.log('ตรวจรายงานรออนุมัติไม่สำเร็จ: %s', e);
  }

  // ตื่นแล้วและข้อมูลปกติ ค่อยทำหน้าที่สะพานส่งข้อมูล กทม.
  // ล้มเหลวตรงนี้ต้องไม่ทำให้การกันหลับพัง มันคนละหน้าที่กัน
  let relayed = '';
  try {
    relayed = relayBMA();
  } catch (e) {
    Logger.log('รีเลย์ กทม. ล้มเหลว: %s', e);
    relayed = 'รีเลย์ล้มเหลว';
  }

  // Written to the log as well as returned: running keepAwake by hand shows
  // only what was logged, and the relay's outcome is the reason to run it.
  Logger.log('สรุปรอบนี้: %s', summary + (relayed ? ' | ' + relayed : ''));
  return summary + (relayed ? ' | ' + relayed : '');
}

/**
 * รีเลย์ข้อมูลระดับน้ำคลองของ กทม. เข้าเว็บเรา
 *
 * เซิร์ฟเวอร์เราอยู่สิงคโปร์และเว็บ กทม. ไม่รับการเชื่อมต่อจากต่างประเทศ
 * (ไม่ใช่ถูกปฏิเสธ แต่ต่อไม่ติดเลย) สคริปต์นี้รันบนเครื่องของ Google
 * ซึ่งถ้าต่อได้ ก็ทำหน้าที่เป็นสะพานส่งข้อมูลเข้ามาแทน
 *
 * ตัวสคริปต์เป็นแค่ท่อ ไม่แกะข้อมูลเอง — ส่งหน้าเว็บดิบ ๆ เข้าไปให้เซิร์ฟเวอร์แกะ
 * เพราะโค้ดแกะข้อมูลมีเทสคุมอยู่แล้ว และถ้าหน้าเว็บ กทม. เปลี่ยนโครงสร้าง
 * จะได้แก้ที่เดียว ไม่ต้องมาไล่แก้สคริปต์ในบัญชี Google ของใครอีกคน
 *
 * ยกเว้นพิกัด ซึ่งอยู่ในหน้าใหญ่ 876 KB ต่อสถานี ไม่คุ้มจะส่งเข้าไป 300 รอบ
 * เพื่อตัวเลขสองตัวที่ไม่เคยเปลี่ยน จึงแกะตรงนี้แล้วส่งไปครั้งเดียว
 */
function relayBMA() {
  if (!INGEST_TOKEN) {
    // Logged, not only returned. keepAwake's return value is not written to
    // the log when the function is run by hand, so this was the one path that
    // produced no output at all — and it is the most likely one during setup.
    Logger.log('ข้ามการรีเลย์: ยังไม่ได้ใส่ INGEST_TOKEN');
    return 'ไม่ได้ตั้ง INGEST_TOKEN — ข้ามการรีเลย์';
  }

  let summary;
  try {
    summary = UrlFetchApp.fetch(BMA_BASE + '/Summary', { muteHttpExceptions: true });
  } catch (e) {
    Logger.log('ต่อเว็บ กทม. ไม่ได้: %s', e);
    return 'ต่อเว็บ กทม. ไม่ได้';
  }
  if (summary.getResponseCode() !== 200) {
    // เว็บเขาจำกัดจำนวนครั้ง เจอ 403 เป็นครั้งคราวถือว่าปกติ รอบหน้าค่อยลองใหม่
    // String(): Logger.log("%s", 403) prints "403.0" in Apps Script.
    Logger.log('เว็บ กทม. ตอบ HTTP %s', String(summary.getResponseCode()));
    return 'กทม. ตอบ HTTP ' + summary.getResponseCode();
  }

  // สถานีที่เว็บเราบอกไว้รอบที่แล้วว่ายังไม่มีพิกัด
  const store = PropertiesService.getScriptProperties();
  const pending = JSON.parse(store.getProperty('need_coords') || '[]');
  const coords = {};
  for (const id of pending.slice(0, COORDS_PER_RUN)) {
    try {
      const page = UrlFetchApp.fetch(BMA_BASE + '/StationDetail?id=' + encodeURIComponent(id),
                                     { muteHttpExceptions: true });
      if (page.getResponseCode() !== 200) continue;
      // รูปแบบเดียวกับที่เซิร์ฟเวอร์ใช้: ละติจูด 12-15, ลองจิจูด 90-109
      const m = page.getContentText()
        .match(/(1[2-5]\.\d{4,})\s*,\s*(9\d\.\d{4,}|10\d\.\d{4,})/);
      if (m) coords[id] = { lat: Number(m[1]), lng: Number(m[2]) };
    } catch (e) {
      Logger.log('ดึงพิกัดสถานี %s ไม่ได้: %s', String(id), e);
    }
    Utilities.sleep(COORDS_DELAY_MS);   // เว็บของหน่วยงานอื่น ค่อย ๆ ขอ
  }

  const res = UrlFetchApp.fetch(BASE_URL + '/api/stations/bma/ingest', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + INGEST_TOKEN },
    payload: JSON.stringify({ summary_html: summary.getContentText(), coords: coords }),
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() !== 200) {
    Logger.log('ส่งเข้าเว็บไม่สำเร็จ: HTTP %s %s',
               res.getResponseCode(), res.getContentText().slice(0, 200));
    return 'ส่งเข้าเว็บไม่สำเร็จ';
  }

  const out = JSON.parse(res.getContentText());
  store.setProperty('need_coords', JSON.stringify(out.need_coords || []));
  const line = 'รีเลย์ กทม.: ใหม่ ' + out.created + ' อัปเดต ' + out.updated +
               ' พิกัดใหม่ ' + out.coords_accepted + ' ยังขาดพิกัด ' +
               (out.need_coords || []).length;
  Logger.log(line);
  return line;
}

/** ทดสอบว่า Google ต่อเว็บ กทม. ได้ไหม — รันครั้งเดียวเพื่อดูผล */
function testBMA() {
  try {
    const res = UrlFetchApp.fetch(BMA_BASE + '/Summary', { muteHttpExceptions: true });
    Logger.log('HTTP %s · ขนาด %s ตัวอักษร', res.getResponseCode(),
               res.getContentText().length);
  } catch (e) {
    Logger.log('ต่อไม่ได้: %s', e);
  }
}

/**
 * เตือนเมื่อมีรายงานรออนุมัติ
 *
 * รายงานที่ไม่เข้าเกณฑ์ขึ้นแผนที่อัตโนมัติ (ไม่มีรูป และยังไม่มีคนที่สองยืนยัน)
 * จะค้างอยู่ในคิวจนกว่าจะมีคนกด ซึ่งเดิมรู้ได้ทางเดียวคือเปิดหน้าผู้ดูแลเอง
 * คืนที่ฝนถล่มคือคืนที่มีคนแจ้งเยอะที่สุด และเป็นคืนที่ผู้ดูแลหลับ
 *
 * เตือนเมื่อจำนวนเพิ่มขึ้น หรือเมื่อค้างอยู่นานเกิน PENDING_REMINDER_MINUTES
 * ไม่ใช่ย้ำเรื่องเดิมทุก 10 นาทีจนคนเลิกอ่าน
 */
function checkPending() {
  const stats = fetchJson('/api/stats/summary');
  if (!stats.ok) {
    Logger.log('อ่านสถิติไม่ได้: %s', stats.error);
    return;
  }

  const pending = Number(stats.data.pending_moderation || 0);
  const store = PropertiesService.getScriptProperties();
  const lastCount = Number(store.getProperty('pending_count') || 0);
  const lastAt = Number(store.getProperty('pending_at') || 0);
  const now = Date.now();

  if (pending === 0) {
    // คิวว่างแล้ว ล้างสถานะเพื่อให้รายการถัดไปเตือนได้ทันที
    store.deleteProperty('pending_count');
    store.deleteProperty('pending_at');
    return;
  }

  const grew = pending > lastCount;
  const overdue = now - lastAt > PENDING_REMINDER_MINUTES * 60 * 1000;
  if (!grew && !overdue) return;

  const subject = 'FloodWatch TH: มีรายงานรออนุมัติ ' + pending + ' รายการ';
  const body = [
    'มีคนแจ้งน้ำท่วมเข้ามาและยังไม่ขึ้นแผนที่ รอให้คุณกดอนุมัติ',
    '',
    'รออนุมัติ: ' + pending + ' รายการ',
    'ขึ้นแผนที่อยู่: ' + (stats.data.active_reports || 0) + ' รายการ',
    'แจ้งเข้ามาใน 24 ชม.: ' + (stats.data.reports_last_24h || 0) + ' รายการ',
    '',
    'กดอนุมัติที่ ' + BASE_URL + '/admin',
    '',
    'รายงานที่มีรูปจะขึ้นแผนที่เองทันที ที่ค้างอยู่ในคิวคือรายการที่ระบบยังไม่มั่นใจ',
  ].join(NEWLINE);

  notify(subject, body);
  store.setProperty('pending_count', String(pending));
  store.setProperty('pending_at', String(now));
  Logger.log('แจ้งเตือน: รออนุมัติ %s รายการ', String(pending));
}

/**
 * แจ้งเตือนรายงานใหม่ที่ขึ้นแผนที่ไปแล้ว
 *
 * checkPending() ดูแต่คิวรออนุมัติ ซึ่งตั้งแต่บังคับแนบรูป รายงานจากคนทั่วไป
 * จะขึ้นแผนที่เองทันที คิวจึงเป็นศูนย์ตลอดและเจ้าของแอปไม่เคยได้รับแจ้งเตือน
 * อะไรเลย ทั้งที่ของที่ต้องรู้เปลี่ยนไปแล้ว: ไม่ใช่ "มีอะไรรอคุณกด" แต่เป็น
 * "มีอะไรขึ้นแผนที่ไปแล้วโดยที่คุณยังไม่เห็น"
 *
 * เตือนตามรหัสรายงานที่เคยเห็น ไม่ใช่ตามจำนวน เพราะจำนวนลดลงได้เมื่อรายงานเก่า
 * หมดอายุ แล้วรายงานใหม่จะเงียบไปด้วย
 */
function checkNewReports() {
  const res = fetchJson('/api/reports?limit=10');
  if (!res.ok) {
    Logger.log('อ่านรายงานไม่ได้: %s', res.error);
    return;
  }

  const rows = Array.isArray(res.data) ? res.data : (res.data.items || []);
  if (!rows.length) return;

  const store = PropertiesService.getScriptProperties();
  const seenRaw = store.getProperty('seen_report_ids') || '';
  const seen = seenRaw ? seenRaw.split(',') : [];

  const fresh = rows.filter(function (r) {
    return r && r.id && seen.indexOf(r.id) === -1;
  });

  // ครั้งแรกสุดยังไม่เคยจำอะไรไว้ ถ้าเตือนเลยจะได้ข้อความยาวเหยียดของเก่าทั้งหมด
  // จำไว้เฉย ๆ แล้วเริ่มเตือนจากรายการถัดไป
  const firstRun = seen.length === 0;

  const ids = rows.map(function (r) { return r.id; }).slice(0, 40);
  store.setProperty('seen_report_ids', ids.join(','));

  if (firstRun || !fresh.length) {
    if (firstRun) {
      // String() เพราะ Logger แปลงตัวเลขเป็น "10.0" ซึ่งอ่านแล้วสะดุด
      // เป็นอาการเดียวกับที่เคยทำให้ chat id ออกมาเป็น 8.365650438E9 แล้วใช้ไม่ได้
      Logger.log('จำรายงานปัจจุบันไว้ %s รายการ เริ่มเตือนจากรายการถัดไป', String(ids.length));
    }
    return;
  }

  const lines = [
    'มีคนแจ้งน้ำท่วมเข้ามาใหม่ และขึ้นแผนที่ไปแล้ว (มีรูปแนบจึงไม่ต้องรออนุมัติ)',
    '',
  ];
  fresh.slice(0, 5).forEach(function (r) {
    const where = r.place || r.district || r.province_name || 'ไม่ระบุจุด';
    const who = r.reporter_name ? ' โดย ' + r.reporter_name : '';
    lines.push('• ' + where + ' — ' + (r.level_label || r.level || '') + who);
  });
  if (fresh.length > 5) lines.push('• และอีก ' + (fresh.length - 5) + ' รายการ');
  lines.push('');
  lines.push('ดูบนแผนที่ ' + BASE_URL);
  lines.push('ถ้าเป็นรายงานที่ไม่จริงหรือไม่เหมาะสม ลบได้ที่ ' + BASE_URL + '/admin');

  notify('FloodWatch TH: มีรายงานใหม่ ' + fresh.length + ' รายการ', lines.join(NEWLINE));
  Logger.log('แจ้งเตือนรายงานใหม่ %s รายการ', String(fresh.length));
}

/** ส่งทั้งอีเมลและ Telegram (ถ้าตั้งค่าไว้) */
function notify(subject, body) {
  const to = Session.getActiveUser().getEmail();
  if (to) {
    try {
      MailApp.sendEmail(to, subject, body);
    } catch (e) {
      Logger.log('ส่งอีเมลไม่สำเร็จ: %s', e);
    }
  }
  sendTelegram(subject + NEWLINE + NEWLINE + body);
}

/** ส่งข้อความเข้า Telegram — เงียบไปถ้ายังไม่ได้ตั้งค่า */
function sendTelegram(text) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  try {
    UrlFetchApp.fetch(
      'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage',
      {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify({
          chat_id: TELEGRAM_CHAT_ID,
          text: text,
          disable_web_page_preview: true,
        }),
        muteHttpExceptions: true,
      });
  } catch (e) {
    Logger.log('ส่ง Telegram ไม่สำเร็จ: %s', e);
  }
}

/**
 * หาเลขห้องแชทของคุณ — ทักหาบอทหนึ่งข้อความก่อน แล้วรันฟังก์ชันนี้
 * เลขที่ได้เอาไปใส่ TELEGRAM_CHAT_ID ด้านบน
 *
 * บอกสาเหตุเมื่อหาไม่เจอ ไม่ใช่แค่บอกว่าไม่เจอ: โทเคนของบอทคนละตัว
 * กับการยังไม่ได้ทักบอท ให้ผลเหมือนกันทุกประการ แต่แก้คนละแบบ
 */
function telegramChatId() {
  if (!TELEGRAM_BOT_TOKEN) {
    Logger.log('ยังไม่ได้ใส่ TELEGRAM_BOT_TOKEN');
    return;
  }
  const api = 'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/';

  // โทเคนนี้เป็นของบอทตัวไหน — คำถามแรกที่ต้องตอบ
  const me = JSON.parse(
    UrlFetchApp.fetch(api + 'getMe', { muteHttpExceptions: true }).getContentText());
  if (!me.ok) {
    Logger.log('โทเคนใช้ไม่ได้: %s', me.description || JSON.stringify(me));
    return;
  }
  Logger.log('โทเคนนี้เป็นของบอท: @%s (%s)', me.result.username, me.result.first_name);

  const res = UrlFetchApp.fetch(api + 'getUpdates', { muteHttpExceptions: true });
  const data = JSON.parse(res.getContentText());
  if (!data.ok) {
    Logger.log('Telegram ปฏิเสธ: %s', data.description || JSON.stringify(data));
    return;
  }

  const updates = data.result || [];
  if (!updates.length) {
    // ถ้าตั้ง webhook ไว้ Telegram จะส่งข้อความไปทางนั้นแทน getUpdates จะว่างเสมอ
    const hook = JSON.parse(
      UrlFetchApp.fetch(api + 'getWebhookInfo', { muteHttpExceptions: true }).getContentText());
    if (hook.ok && hook.result && hook.result.url) {
      Logger.log('บอทตัวนี้ตั้ง webhook ไว้ที่ %s — ข้อความจึงไม่มาทางนี้', hook.result.url);
      return;
    }
    Logger.log('ยังไม่เห็นข้อความจาก @%s — ทักหาบอท "ตัวนี้" หนึ่งข้อความก่อน แล้วรันใหม่',
               me.result.username);
    return;
  }

  const chat = updates[updates.length - 1].message.chat;
  // String() first: Apps Script formats a large number as 8.365650438E9, and
  // pasting that into TELEGRAM_CHAT_ID fails silently — no error, just no
  // messages ever arriving.
  Logger.log('เลขห้องแชทของคุณคือ %s (%s)',
             String(chat.id), chat.first_name || chat.title || '');
  Logger.log('ใส่แบบนี้ -> const TELEGRAM_CHAT_ID = "%s";', String(chat.id));
  return String(chat.id);
}

/**
 * ส่งข้อความทดสอบเข้า Telegram — รันหลังตั้งค่าเสร็จเพื่อยืนยันว่าถึงจริง
 * "ตั้งค่าแล้ว" กับ "ข้อความถึงจริง" เป็นคนละเรื่อง และเรื่องหลังคือเรื่องที่สำคัญ
 */
function testTelegram() {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
    Logger.log('ยังไม่ได้ตั้ง TELEGRAM_BOT_TOKEN หรือ TELEGRAM_CHAT_ID');
    return;
  }
  const res = UrlFetchApp.fetch(
    'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage',
    {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({
        chat_id: TELEGRAM_CHAT_ID,
        text: 'FloodWatch TH: ทดสอบการแจ้งเตือน ถ้าเห็นข้อความนี้แปลว่าตั้งค่าถูกแล้ว',
      }),
      muteHttpExceptions: true,
    });
  const data = JSON.parse(res.getContentText());
  if (data.ok) {
    Logger.log('ส่งสำเร็จ — ไปดูใน Telegram ได้เลย');
  } else {
    Logger.log('ส่งไม่สำเร็จ: %s', data.description || res.getContentText());
  }
}

/** ดึง JSON จาก API ของเรา คืน {ok, data} หรือ {ok:false, error} */
/**
 * เหตุผลที่ควรเตือนเรื่องข้อมูลระดับน้ำ หรือ null ถ้าไม่ต้องเตือน
 * แยกออกมาเป็นฟังก์ชันล้วน ๆ เพื่อให้ทดสอบได้ (backend/test_keepalive_alert.cjs)
 */
function staleAlertReason(s) {
  const failed = Object.keys(s.sources || {}).filter(function (name) {
    return s.sources[name] && s.sources[name].ok === false;
  });
  if (failed.length) {
    return 'การซิงก์ของเราล้มเหลว — ' + describeSyncErrors(s.sources);
  }
  const ageH = ageInHours(s.newest_measured_at);
  if (ageH !== null && ageH > SOURCE_QUIET_ALERT_HOURS) {
    return 'ต้นทางไม่มีข้อมูลใหม่มา ' + ageH.toFixed(1) + ' ชม. ' +
           '(ปกติเงียบข้ามคืนแล้วกลับมาช่วงเช้า เกินกว่านี้ผิดปกติ)';
  }
  // ไม่รู้เวลาที่วัดเลย แปลว่าฐานข้อมูลว่างหรือ API เก่า — อันนี้ควรรู้
  if (ageH === null && !s.total) {
    return 'ไม่มีสถานีในระบบเลย';
  }
  return null;
}

/** อายุของเวลาที่ให้มา เป็นชั่วโมง คืน null ถ้าอ่านไม่ได้ */
function ageInHours(iso) {
  if (!iso) return null;
  // เวลาจากเซิร์ฟเวอร์เป็น UTC แต่บางครั้งไม่มีตัว Z ต่อท้าย ถ้าไม่เติมให้
  // เครื่องจะตีความเป็นเวลาไทย แล้วได้อายุติดลบ 7 ชม. — กลายเป็นไม่เตือนเลย
  const text = /[Z+]|[0-9]-[0-9]{2}:[0-9]{2}$/.test(iso) ? iso : iso + 'Z';
  const at = new Date(text).getTime();
  if (isNaN(at)) return null;
  return (Date.now() - at) / 3600000;
}

/** ข้อความสั้น ๆ ว่าแหล่งไหนพังเพราะอะไร */
function describeSyncErrors(sources) {
  const parts = [];
  Object.keys(sources || {}).forEach(function (name) {
    const entry = sources[name];
    if (entry && entry.ok === false) {
      parts.push(name + ': ' + (entry.error || 'ไม่ทราบสาเหตุ'));
    }
  });
  return parts.length ? parts.join(' · ') : 'ไม่ทราบสาเหตุ';
}

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

  notify(subject, body);
  store.setProperty(prop, String(now));
}

/** ปัญหาหายแล้ว รีเซ็ตเพื่อให้ครั้งหน้าแจ้งได้ทันที */
function clearAlert(key) {
  PropertiesService.getScriptProperties().deleteProperty('alerted_' + key);
}


// ===================================================================== สำรองข้อมูล
//
// ฐานข้อมูลอยู่ที่ Neon แพ็กฟรีย้อนเวลากู้คืนได้แค่ช่วงสั้น ๆ ส่วนนี้ดาวน์โหลด
// CSV ทุกคืนเก็บไว้ใน Google Drive โฟลเดอร์ "FloodWatch Backup" แยกตามวันที่
// (ไม่มี IP หรือชื่อผู้แจ้งในไฟล์ — เซิร์ฟเวอร์ตัดออกให้ก่อนส่ง)
//
// วิธีตั้ง (ทำครั้งเดียว):
//   1. Render → Environment → เพิ่ม BACKUP_TOKEN (ตั้งเป็นข้อความสุ่มยาว ๆ) → Save
//   2. เอาค่าเดียวกันมาใส่ช่องล่าง
//   3. เลือกฟังก์ชัน setupBackup แล้วกด Run (จะขออนุญาตเข้า Drive ให้กดอนุญาต)
//
// ถ้าวางไฟล์นี้ทับของเดิม อย่าลืมใส่ INGEST_TOKEN / TELEGRAM_* กลับด้วย
// หรือจะคัดลอกแค่ส่วนนี้ไปต่อท้ายสคริปต์เดิมก็ได้

const BACKUP_TOKEN = '';
const BACKUP_FOLDER = 'FloodWatch Backup';
// เก็บย้อนหลังกี่วัน เก่ากว่านี้ย้ายลงถังขยะของ Drive (กู้คืนได้อีก 30 วัน)
const BACKUP_KEEP_DAYS = 60;

function setupBackup() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'backupToDrive')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  // ตีสามเวลาไทย: คนใช้น้อยที่สุด และเป็นข้อมูลครบของเมื่อวาน
  ScriptApp.newTrigger('backupToDrive').timeBased().everyDays(1).atHour(3)
    .inTimezone('Asia/Bangkok').create();
  const result = backupToDrive();
  Logger.log('ตั้ง backup ทุกคืนตีสามแล้ว — ผลครั้งแรก: %s', String(result));
  return result;
}

function backupToDrive() {
  if (!BACKUP_TOKEN) {
    Logger.log('ยังไม่ได้ใส่ BACKUP_TOKEN — ข้าม');
    return 'ยังไม่ได้ใส่ BACKUP_TOKEN';
  }
  const folders = DriveApp.getFoldersByName(BACKUP_FOLDER);
  const root = folders.hasNext() ? folders.next() : DriveApp.createFolder(BACKUP_FOLDER);
  const day = Utilities.formatDate(new Date(), 'Asia/Bangkok', 'yyyy-MM-dd');

  const saved = [];
  for (const name of ['reports', 'visits', 'tallies']) {
    const res = UrlFetchApp.fetch(BASE_URL + '/api/admin/export/' + name + '.csv', {
      headers: { Authorization: 'Bearer ' + BACKUP_TOKEN },
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code !== 200) {
      // ไม่ใส่เนื้อหาคำตอบลงอีเมล: กันไม่ให้อะไรที่ไม่ควรหลุดติดไปด้วย
      alertOnce('backup', 'FloodWatch: สำรองข้อมูลไม่สำเร็จ',
        'ดาวน์โหลด ' + name + '.csv ได้ HTTP ' + code +
        (code === 401 ? ' — BACKUP_TOKEN ในสคริปต์ไม่ตรงกับใน Render' : ''));
      return 'ล้มเหลวที่ ' + name + ' (HTTP ' + code + ')';
    }
    const fileName = 'floodwatch-' + name + '-' + day + '.csv';
    const old = root.getFilesByName(fileName);
    while (old.hasNext()) old.next().setTrashed(true);  // รันซ้ำวันเดียวกัน = แทนที่
    root.createFile(res.getBlob().setName(fileName));
    saved.push(name);
  }
  clearAlert('backup');

  const cutoff = Date.now() - BACKUP_KEEP_DAYS * 24 * 3600 * 1000;
  const files = root.getFiles();
  let trashed = 0;
  while (files.hasNext()) {
    const f = files.next();
    if (f.getName().indexOf('floodwatch-') === 0 && f.getDateCreated().getTime() < cutoff) {
      f.setTrashed(true);
      trashed++;
    }
  }
  const line = 'สำรองแล้ว ' + saved.join(', ') + ' (' + day + ')' +
    (trashed ? ' · ลบไฟล์เก่า ' + trashed + ' ไฟล์' : '');
  Logger.log(line);
  return line;
}
