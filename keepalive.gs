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

/**
 * โทเคนสำหรับส่งข้อมูล กทม. เข้าเว็บ ต้องตรงกับ INGEST_TOKEN ที่ตั้งไว้ใน Render
 * เว้นว่างไว้ = ไม่ทำหน้าที่รีเลย์ ยิงกันหลับอย่างเดียว
 */
const INGEST_TOKEN = '';

/** หน้าเว็บของสำนักการระบายน้ำ กทม. ที่เซิร์ฟเวอร์เราเข้าไม่ถึงจากต่างประเทศ */
const BMA_BASE = 'https://weather.bangkok.go.th/water';

/**
 * ดึงหน้ารายละเอียดกี่สถานีต่อรอบ เอาไว้เก็บพิกัด
 * หน้าละ ~876 KB จึงค่อย ๆ เก็บ ไม่รีบ เพราะพิกัดเก็บครั้งเดียวใช้ตลอด
 * และเว็บเขามีการจำกัดจำนวนครั้ง ยิงรัวจะโดนปฏิเสธ
 */
const COORDS_PER_RUN = 5;

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

  // ตื่นแล้วและข้อมูลปกติ ค่อยทำหน้าที่สะพานส่งข้อมูล กทม.
  // ล้มเหลวตรงนี้ต้องไม่ทำให้การกันหลับพัง มันคนละหน้าที่กัน
  let relayed = '';
  try {
    relayed = relayBMA();
  } catch (e) {
    Logger.log('รีเลย์ กทม. ล้มเหลว: %s', e);
    relayed = 'รีเลย์ล้มเหลว';
  }

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
  if (!INGEST_TOKEN) return 'ไม่ได้ตั้ง INGEST_TOKEN — ข้ามการรีเลย์';

  let summary;
  try {
    summary = UrlFetchApp.fetch(BMA_BASE + '/Summary', { muteHttpExceptions: true });
  } catch (e) {
    Logger.log('ต่อเว็บ กทม. ไม่ได้: %s', e);
    return 'ต่อเว็บ กทม. ไม่ได้';
  }
  if (summary.getResponseCode() !== 200) {
    // เว็บเขาจำกัดจำนวนครั้ง เจอ 403 เป็นครั้งคราวถือว่าปกติ รอบหน้าค่อยลองใหม่
    Logger.log('เว็บ กทม. ตอบ HTTP %s', summary.getResponseCode());
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
      Logger.log('ดึงพิกัดสถานี %s ไม่ได้: %s', id, e);
    }
    Utilities.sleep(400);   // เว็บของหน่วยงานอื่น ค่อย ๆ ขอ
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
