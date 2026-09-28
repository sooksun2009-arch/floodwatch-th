/**
 * Thai and English, for a map that people from outside Thailand need too.
 *
 * Two rules shape this file.
 *
 * The first is that nothing here translates what a person wrote. Report text,
 * place names and reporter names arrive in whichever language they were typed
 * in and are shown that way, labelled. Machine-translating "น้ำลึกช่วงหน้าปั๊ม
 * รถเก๋งอย่าเข้า" for someone about to drive into it is a worse outcome than
 * showing them Thai and saying so.
 *
 * The second is that English readers get depths in inches beside centimetres.
 * "30 cm" is a number; "12 in" is a decision about whether to drive.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const STORE_KEY = 'floodwatch.lang'

const STRINGS = {
  th: {
    'app.tagline': 'จะไปไหน เช็คก่อนออกรถ',
    'nav.route': 'เช็คเส้นทาง',
    'nav.cameras': 'กล้อง CCTV',
    'nav.stats': 'ภาพรวม',
    'nav.admin': 'ผู้ดูแล',
    'nav.login': 'เข้าสู่ระบบ',
    'nav.logout': 'ออก',
    'nav.share': 'แชร์',
    'share.copied': 'คัดลอกลิงก์แล้ว',

    'safety.body': 'แอปนี้ทำโดยบุคคลทั่วไป <b>ไม่ใช่หน่วยงานราชการ</b> และไม่ใช่ช่องทางขอความช่วยเหลือ',
    'safety.urgent': 'เหตุด่วน',
    'safety.call': 'โทร 1784',
    'safety.bkk': 'ปภ. · ในกรุงเทพฯ',

    'route.title': 'จะไปไหน เช็คก่อนออกรถ',
    'route.how': 'วิธีการใช้งาน',
    'route.from': 'ต้นทาง',
    'route.to': 'ปลายทาง',
    'route.fromPlaceholder': 'เช่น บางนา, ถนนรามคำแหง',
    'route.toPlaceholder': 'เช่น ลาดพร้าว, จตุจักร',
    'route.swap': 'สลับ',
    'route.check': 'เช็คเส้นทางนี้',
    'route.checking': 'กำลังเช็ค…',
    'route.needOrigin': 'กรุณาระบุต้นทาง',
    'route.needDest': 'กรุณาระบุปลายทาง',
    'route.pickOnMap': 'เลือกจุดบนแผนที่',
    'route.useMyLocation': 'ใช้ตำแหน่งของฉัน',
    'route.distance': 'ระยะทาง',
    'route.duration': 'ใช้เวลาประมาณ',
    'route.km': 'กม.',
    'route.min': 'นาที',
    'route.obstacles': 'จุดที่ต้องระวังบนเส้นทาง',
    'route.noObstacles': 'ไม่พบรายงานน้ำท่วมบนเส้นทาง',
    'route.atKm': 'กม. ที่',
    'route.offRoute': 'ห่างจากเส้นทาง',
    'route.m': 'ม.',
    'route.confirms': 'ยืนยัน',
    'route.noConfirms': 'ยังไม่มีผู้ยืนยัน',
    'route.people': 'ราย',
    'route.cameras': 'กล้อง CCTV ตามเส้นทาง',
    'route.noCameras': 'ยังไม่มีกล้อง CCTV ที่ลงทะเบียนไว้ตามเส้นทางนี้',
    'route.gauges': 'คลอง/แม่น้ำใกล้เส้นทางที่กำลังล้นตลิ่ง',
    'route.aboveBank': 'สูงกว่าตลิ่ง',

    'verdict.clear': 'ไปได้',
    'verdict.caution': 'ไปได้ ระวัง',
    'verdict.risky': 'เสี่ยง',
    'verdict.blocked': 'ไม่ควรไป',
    'verdict.clear.sub': 'ไม่พบรายงานน้ำท่วมบนเส้นทาง',
    'verdict.caution.sub': 'ผ่านได้ แต่มีน้ำขังบางจุด',
    'verdict.risky.sub': 'เสี่ยง มีจุดน้ำลึกที่รถเก๋งอาจไม่รอด',
    'verdict.blocked.sub': 'ไม่ควรใช้เส้นทางนี้ มีจุดที่ผ่านไม่ได้',
    'verdict.caveat': 'หมายถึงยังไม่มีใครแจ้ง ไม่ใช่การยืนยันว่าถนนแห้ง',

    'level.normal': 'สัญจรได้ปกติ',
    'level.puddle': 'น้ำขังผิวถนน ไม่เกิน 10 ซม.',
    'level.shallow': 'น้ำท่วม 10-30 ซม.',
    'level.deep': 'น้ำท่วม 30-60 ซม.',
    'level.severe': 'น้ำท่วมเกิน 60 ซม.',
    'level.closed': 'ปิดการจราจร',
    'level.normal.short': 'ปกติ',
    'level.puddle.short': 'น้ำขัง',
    'level.shallow.short': '10-30 ซม.',
    'level.deep.short': '30-60 ซม.',
    'level.severe.short': 'เกิน 60 ซม.',
    'level.closed.short': 'ปิดถนน',

    'legend.title': 'ระดับน้ำ · กดเพื่อดูเฉพาะที่เลือก',
    'legend.chip': 'สัญลักษณ์',
    'legend.collapse': 'ย่อคำอธิบายสัญลักษณ์',
    'legend.showAll': 'กดเพื่อแสดงทั้งหมด',
    'legend.filtering': 'แสดงเฉพาะ',
    'legend.cameras': 'กล้อง CCTV',
    'legend.gauges': 'คลองเฝ้าระวัง/วิกฤติ',

    'layer.radar': 'เรดาร์ฝน',
    'layer.satellite': 'น้ำท่วมจากดาวเทียม',
    'layer.satellite.caption':
      'พื้นที่สีส้มคือบริเวณที่<b>ดาวเทียมเห็นน้ำใน{span}</b> — ไม่ใช่ภาพสด และ<b>ไม่ได้แปลว่าถนนในนั้นผ่านไม่ได้</b> ถนนยกสูงกลางทุ่งที่น้ำท่วมเป็นเรื่องปกติ',
    'layer.satellite.credit': 'ข้อมูล GISTDA · ใช้ประกอบการตัดสินใจ ไม่ใช่คำยืนยัน',
    'span.1day': 'วันที่ผ่านมา',
    'span.3days': '3 วันที่ผ่านมา',
    'span.7days': '7 วันที่ผ่านมา',
    'span.30days': '30 วันที่ผ่านมา',
    'span.default': 'ช่วงที่ผ่านมา',

    'report.button': 'แจ้งน้ำท่วม',
    'report.title': 'แจ้งจุดน้ำท่วม',
    'report.where': 'ตรงไหน',
    'report.level': 'ลึกแค่ไหน',
    'report.photo': 'รูปถ่าย',
    'report.photoRequired': 'ต้องแนบรูป — รูปช่วยให้คนอื่นตัดสินใจได้จริง',
    'report.note': 'รายละเอียดเพิ่มเติม',
    'report.name': 'ชื่อผู้แจ้ง',
    'report.submit': 'ส่งรายงาน',
    'report.sending': 'กำลังส่ง…',
    'report.stillFlooded': 'ยังท่วมอยู่',
    'report.subsided': 'น้ำลดแล้ว',
    'report.disputes': 'แย้ง',
    'report.confirms': 'ยืนยัน',
    'report.reportedAt': 'แจ้งเมื่อ',
    'report.thaiText': 'ข้อความจากผู้แจ้ง (ภาษาไทย)',

    'age.mayHaveChanged': 'สถานการณ์อาจเปลี่ยนแล้ว',
    'age.old': 'นานแล้ว — ถ้าคุณอยู่แถวนั้น ช่วยกดยืนยันหน่อยครับ',

    'map.loading': 'กำลังโหลดแผนที่…',
    'map.loadFailed': 'โหลดข้อมูลแผนที่ไม่สำเร็จ — ตรวจการเชื่อมต่อแล้วลองใหม่',
    'pick.instruction': 'เลื่อนแผนที่ให้หมุดอยู่ตรง{what}',
    'pick.confirm': 'ยืนยันตำแหน่งนี้',
    'common.cancel': 'ยกเลิก',
    'cams.title': 'กล้อง CCTV',
    'cams.sub': 'ดูภาพจริงด้วยตาตัวเองก่อนตัดสินใจ — วิธีที่เชื่อถือได้ที่สุด',
    'cams.none.title': 'แอปนี้ยังไม่มีกล้องเป็นของตัวเอง',
    'cams.none.body': 'การรวมกล้องจราจรเข้ามาต้องขออนุญาตรายหน่วยงาน ซึ่งยังทำไม่เสร็จ ระหว่างนี้แนะนำให้ดูจากเว็บที่เขารวมไว้แล้ว และเปิดดูได้ฟรี',
    'cams.none.filtered': 'ไม่พบกล้องที่ตรงกับเงื่อนไข',
    'cams.out.longdo': 'Longdo Traffic — กล้องจราจรทั่วประเทศ',
    'cams.out.longdoWhy': 'รวมกล้องของ กทม. ทางด่วน และหน่วยงานอื่นไว้ในหน้าเดียว เลือกดูพร้อมกันได้ 4–16 ตัว',
    'cams.out.longdoMap': 'Longdo Traffic — แผนที่จราจรและจุดน้ำท่วม',
    'cams.out.longdoMapWhy': 'แผนที่สด มีหมุดน้ำท่วมที่ผู้ใช้แจ้ง และกดที่หมุดเพื่อดูภาพกล้องได้',
    'cams.out.note': 'ลิงก์เหล่านี้เป็นของเว็บอื่น ไม่ได้อยู่ในความดูแลของเรา และอาจเปลี่ยนแปลงหรือปิดได้',
    'cams.out.open': 'เปิดเว็บนั้น',
    'popup.measured': 'วัดได้ {depth}',
    'popup.tally': 'ยืนยัน {confirms} · แย้ง {disputes}',
    'popup.photoAlt': 'ภาพจุดน้ำท่วม',
    'popup.photoTitle': 'แตะเพื่อเปิดรูปเต็ม',
    'popup.thanks': 'ขอบคุณครับ',
    'popup.thanksChecking': 'ขอบคุณครับ — จะตรวจสอบให้',
    'popup.sendFailed': 'ส่งไม่สำเร็จ ลองใหม่อีกครั้ง',
    'popup.aboveBank': 'สูงกว่าตลิ่ง {m} ม.',
    'popup.belowBank': 'ต่ำกว่าตลิ่ง {m} ม.',
    'popup.agency': 'ข้อมูลโดย {agency}',
    'popup.stale': 'ข้อมูลไม่อัปเดต',
    'popup.trendLoading': 'กำลังดูแนวโน้ม…',
    'popup.trendNone': 'ไม่มีข้อมูลย้อนหลัง',
    'popup.trendFailed': 'ดูแนวโน้มไม่สำเร็จ',
    'popup.unknownPlace': 'ไม่ระบุจุด',
    'map.error': 'แผนที่ทำงานผิดพลาด',
    'map.layerFailed': 'สร้างชั้นข้อมูลบนแผนที่ไม่สำเร็จ: {message}',
    'ago.now': 'เมื่อสักครู่',
    'ago.min': '{n} นาทีที่แล้ว',
    'ago.hour': '{n} ชม.ที่แล้ว',
    'ago.day': '{n} วันที่แล้ว',
    'age.reported': 'แจ้งเมื่อ {ago}',
    'map.attribution': '© ผู้ร่วมสร้าง OpenStreetMap',
    'rp.gpsUnsupported': 'เบราว์เซอร์นี้ไม่รองรับการระบุตำแหน่ง',
    'rp.gpsDenied': 'คุณปฏิเสธการเข้าถึงตำแหน่ง เปิดสิทธิ์ในเบราว์เซอร์แล้วลองใหม่',
    'rp.gpsFailed': 'ระบุตำแหน่งไม่สำเร็จ ลองพิมพ์ชื่อสถานที่แทน',
    'rp.useGps': 'ใช้ตำแหน่งปัจจุบันของฉัน',
    'rp.pinOnMap': 'ปักหมุดบนแผนที่',
    'rp.tapMap': 'แตะแผนที่',
    'rp.coords': 'พิกัด',
    'rp.close': 'ปิด',
    'rp.understood': 'เข้าใจแล้ว',
    'rp.camerasHeading': 'กล้อง CCTV ตามเส้นทาง',
    'rp.camerasNone': 'ยังไม่มีกล้องในระบบ — ระบบจะแสดงเฉพาะกล้องจริงของหน่วยงานเท่านั้น',
    'rp.camerasStep': '1. ดูด้วยตาตัวเอง — กล้องตามเส้นทาง',
    'rp.sortedByDistance': 'เรียงตามระยะทาง',
    'rp.kmMark': 'กม.',
    'rp.offRoute': 'ห่างเส้นทาง',
    'rp.demoStream': 'สตรีมตัวอย่าง',
    'rp.frozenFrame': 'ภาพค้าง',
    'rp.nearFlood': 'ใกล้จุด',
    'rp.gaugesStep': '3. คลองใกล้เส้นทางที่ล้นตลิ่ง',
    'rp.aboveBankShort': 'สูงกว่าตลิ่ง',
    'rp.agencyShort': 'ข้อมูลโดย',
    'rp.staleShort': 'ข้อมูลไม่อัปเดต',
    'rp.gaugeCaveat': 'เป็นระดับน้ำในคลองที่วัดด้วยเครื่องมือ ไม่ใช่ระดับน้ำบนถนน แต่คลองที่ล้นตลิ่งมักทำให้ถนนใกล้เคียงท่วมตามในเวลาไม่นาน',
    'rp.noReports': 'ไม่มีรายงานน้ำท่วมบนเส้นทางนี้',
    'rp.noReportsCaveat': 'หมายถึงยังไม่มีใครแจ้ง ไม่ใช่การยืนยันว่าถนนแห้ง — ถ้าคุณขับผ่านแล้วเจอน้ำ ช่วยกดแจ้งด้วยครับ',
    'rp.reportsStep': '2. รายงานจากผู้ใช้บนเส้นทาง',
    'rp.unknownSpot': 'ไม่ระบุจุด',
    'rp.measuredShort': 'วัดได้',
    'rp.official': 'ข้อมูลทางการ',
    'rp.checkFailed': 'ตรวจเส้นทางไม่สำเร็จ ลองใหม่อีกครั้ง',
    'rp.voteFailed': 'ส่งความเห็นไม่สำเร็จ',
    'rp.limitsHeading': 'ข้อจำกัดที่ต้องรู้',
    'route.swapTitle': 'สลับต้นทางกับปลายทาง',
    'route.disclosure': 'แหล่งข้อมูล ข้อจำกัด และความเป็นส่วนตัว',
    'byline.by': 'พัฒนาโดย',
    'byline.hire': 'รับเขียนเว็บและระบบภายในองค์กร',
    'lang.switch': 'English',
    'lang.label': 'ภาษา',
  },

  en: {
    'app.tagline': 'Check before you drive',
    'nav.route': 'Check a route',
    'nav.cameras': 'CCTV',
    'nav.stats': 'Overview',
    'nav.admin': 'Admin',
    'nav.login': 'Sign in',
    'nav.logout': 'Sign out',
    'nav.share': 'Share',
    'share.copied': 'Link copied',

    'safety.body':
      'Made by a private individual, <b>not a government agency</b>, and not a way to request help.',
    'safety.urgent': 'Emergency',
    'safety.call': 'Call 1784',
    'safety.bkk': 'Disaster hotline · In Bangkok',

    'route.title': 'Where to? Check before you drive',
    'route.how': 'How to use',
    'route.from': 'From',
    'route.to': 'To',
    'route.fromPlaceholder': 'e.g. Bang Na, Ramkhamhaeng Rd',
    'route.toPlaceholder': 'e.g. Lat Phrao, Chatuchak',
    'route.swap': 'Swap',
    'route.check': 'Check this route',
    'route.checking': 'Checking…',
    'route.needOrigin': 'Please enter a starting point',
    'route.needDest': 'Please enter a destination',
    'route.pickOnMap': 'Pick a point on the map',
    'route.useMyLocation': 'Use my location',
    'route.distance': 'Distance',
    'route.duration': 'About',
    'route.km': 'km',
    'route.min': 'min',
    'route.obstacles': 'Flooding reported along this route',
    'route.noObstacles': 'No flood reports along this route',
    'route.atKm': 'km',
    'route.offRoute': 'off the route',
    'route.m': 'm',
    'route.confirms': 'confirmed by',
    'route.noConfirms': 'not yet confirmed by anyone',
    'route.people': 'people',
    'route.cameras': 'Traffic cameras along the route',
    'route.noCameras': 'No traffic cameras registered along this route yet',
    'route.gauges': 'Canals and rivers over their banks near this route',
    'route.aboveBank': 'above the bank',

    'verdict.clear': 'Looks passable',
    'verdict.caution': 'Passable, take care',
    'verdict.risky': 'Risky',
    'verdict.blocked': 'Do not drive this',
    'verdict.clear.sub': 'No flood reports along this route',
    'verdict.caution.sub': 'Passable, but water is standing in places',
    'verdict.risky.sub': 'Water deep enough that a saloon car may not get through',
    'verdict.blocked.sub': 'This route has a point that cannot be driven',
    'verdict.caveat': 'This means nobody has reported anything — not that the road is dry',

    'level.normal': 'Normal, no water',
    'level.puddle': 'Standing water, under 10 cm (4 in)',
    'level.shallow': 'Flooded 10–30 cm (4–12 in)',
    'level.deep': 'Flooded 30–60 cm (12–24 in)',
    'level.severe': 'Flooded over 60 cm (24 in)',
    'level.closed': 'Road closed',
    'level.normal.short': 'Normal',
    'level.puddle.short': 'Puddles',
    'level.shallow.short': '10–30 cm',
    'level.deep.short': '30–60 cm',
    'level.severe.short': 'Over 60 cm',
    'level.closed.short': 'Closed',

    'legend.title': 'Water depth · tap to show only what you pick',
    'legend.chip': 'Legend',
    'legend.collapse': 'Collapse the legend',
    'legend.showAll': 'Tap to show everything',
    'legend.filtering': 'Showing only',
    'legend.cameras': 'Traffic camera',
    'legend.gauges': 'Canal at warning/critical level',

    'layer.radar': 'Rain radar',
    'layer.satellite': 'Flooding seen from orbit',
    'layer.satellite.caption':
      'Orange marks where a <b>satellite saw water over the {span}</b> — not a live image, and <b>not a claim that roads there are impassable</b>. Raised roads through flooded fields are ordinary in Thailand.',
    'layer.satellite.credit': 'Data from GISTDA · context for your decision, not confirmation',
    'span.1day': 'past day',
    'span.3days': 'past 3 days',
    'span.7days': 'past 7 days',
    'span.30days': 'past 30 days',
    'span.default': 'past few days',

    'report.button': 'Report flooding',
    'report.title': 'Report a flooded spot',
    'report.where': 'Where',
    'report.level': 'How deep',
    'report.photo': 'Photo',
    'report.photoRequired': 'A photo is required — it is what lets other people judge for themselves',
    'report.note': 'Anything else',
    'report.name': 'Your name',
    'report.submit': 'Send report',
    'report.sending': 'Sending…',
    'report.stillFlooded': 'Still flooded',
    'report.subsided': 'Water has gone',
    'report.disputes': 'disputed',
    'report.confirms': 'confirmed',
    'report.reportedAt': 'Reported',
    'report.thaiText': 'Note from the reporter (in Thai)',

    'age.mayHaveChanged': 'This may have changed since',
    'age.old': 'Reported a while ago — if you are nearby, please confirm',

    'map.loading': 'Loading the map…',
    'map.loadFailed': 'Could not load map data — check your connection and try again',
    'pick.instruction': 'Move the map so the pin sits on your {what}',
    'pick.confirm': 'Use this spot',
    'common.cancel': 'Cancel',
    'cams.title': 'Traffic cameras',
    'cams.sub': 'Seeing the road yourself is the most reliable check there is',
    'cams.none.title': 'This app does not have its own cameras yet',
    'cams.none.body': 'Carrying traffic camera feeds means asking each agency for permission, which is not done. In the meantime these sites already collect them, and they are free to watch.',
    'cams.none.filtered': 'No cameras match that search',
    'cams.out.longdo': 'Longdo Traffic — cameras across Thailand',
    'cams.out.longdoWhy': 'Bangkok city, expressway and other agencies on one page; watch 4 to 16 at once.',
    'cams.out.longdoMap': 'Longdo Traffic — live traffic and flood map',
    'cams.out.longdoMapWhy': 'A live map with user-reported flooding; tap a marker to see that camera.',
    'cams.out.note': 'These are other people’s sites, outside our control, and they may change or close.',
    'cams.out.open': 'Open that site',
    'popup.measured': 'Measured {depth}',
    'popup.tally': '{confirms} confirmed · {disputes} disputed',
    'popup.photoAlt': 'Photo of the flooded spot',
    'popup.photoTitle': 'Tap to see the full photo',
    'popup.thanks': 'Thank you',
    'popup.thanksChecking': 'Thank you — we will look into it',
    'popup.sendFailed': 'Could not send that. Please try again.',
    'popup.aboveBank': '{m} m above the bank',
    'popup.belowBank': '{m} m below the bank',
    'popup.agency': 'Data from {agency}',
    'popup.stale': 'Reading is out of date',
    'popup.trendLoading': 'Loading the trend…',
    'popup.trendNone': 'No recent history',
    'popup.trendFailed': 'Could not load the trend',
    'popup.unknownPlace': 'Location not given',
    'map.error': 'The map hit a problem',
    'map.layerFailed': 'Could not build the map layers: {message}',
    'ago.now': 'just now',
    'ago.min': '{n} min ago',
    'ago.hour': '{n} hr ago',
    'ago.day': '{n} days ago',
    'age.reported': 'Reported {ago}',
    'map.attribution': '© OpenStreetMap contributors',
    'rp.gpsUnsupported': 'This browser cannot find your location',
    'rp.gpsDenied': 'Location access was refused. Allow it in your browser and try again.',
    'rp.gpsFailed': 'Could not find your location. Try typing a place name instead.',
    'rp.useGps': 'Use my current location',
    'rp.pinOnMap': 'Drop a pin on the map',
    'rp.tapMap': 'Tap the map',
    'rp.coords': 'Coordinates',
    'rp.close': 'Close',
    'rp.understood': 'Got it',
    'rp.camerasHeading': 'Traffic cameras along the route',
    'rp.camerasNone': 'No cameras in this app yet — only real agency cameras are ever shown',
    'rp.camerasStep': '1. See for yourself — cameras along the route',
    'rp.sortedByDistance': 'In order along the route',
    'rp.kmMark': 'km',
    'rp.offRoute': 'off the route',
    'rp.demoStream': 'Sample stream',
    'rp.frozenFrame': 'Frame frozen for',
    'rp.nearFlood': 'Near flooding:',
    'rp.gaugesStep': '3. Canals over their banks near the route',
    'rp.aboveBankShort': 'above the bank',
    'rp.agencyShort': 'Data from',
    'rp.staleShort': 'Out of date',
    'rp.gaugeCaveat': 'This is the water level in the canal, measured by instrument — not the level on the road. A canal over its bank often floods nearby roads before long.',
    'rp.noReports': 'No flood reports on this route',
    'rp.noReportsCaveat': 'That means nobody has reported anything, not that the road is dry. If you drive it and find water, please report it.',
    'rp.reportsStep': '2. Reports from people on this route',
    'rp.unknownSpot': 'Location not given',
    'rp.measuredShort': 'measured',
    'rp.official': 'Official',
    'rp.checkFailed': 'Could not check that route. Please try again.',
    'rp.voteFailed': 'Could not send that',
    'rp.limitsHeading': 'What this cannot tell you',
    'route.swapTitle': 'Swap start and destination',
    'route.disclosure': 'Sources, limitations and privacy',
    'byline.by': 'Built by',
    'byline.hire': 'available for web and internal systems work',
    'lang.switch': 'ไทย',
    'lang.label': 'Language',
  },
}

const LANGS = ['th', 'en']

function detect() {
  try {
    const saved = localStorage.getItem(STORE_KEY)
    if (LANGS.includes(saved)) return saved
  } catch {
    // Private windows and blocked site data throw here. Not a reason to fail.
  }
  // Thai for everyone who has not chosen otherwise, including visitors whose
  // browser asks for English. Guessing from the browser's language was the
  // first version and it is wrong for this audience: plenty of people in
  // Thailand run their phone in English and would rather read a Thai flood
  // map in Thai. A visitor who needs English sees "EN" in the header, which
  // is legible whatever language you read.
  return 'th'
}

const Ctx = createContext({ lang: 'th', t: (k) => k, setLang: () => {} })

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(detect)

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((next) => {
    if (!LANGS.includes(next)) return
    setLangState(next)
    try {
      localStorage.setItem(STORE_KEY, next)
    } catch {
      // A viewer who cannot persist the choice still gets it for this visit.
    }
  }, [])

  const t = useCallback(
    (key, vars) => {
      let text = STRINGS[lang]?.[key] ?? STRINGS.th[key] ?? key
      if (vars) {
        for (const [name, value] of Object.entries(vars)) {
          text = text.split(`{${name}}`).join(String(value))
        }
      }
      return text
    },
    [lang],
  )

  const value = useMemo(() => ({ lang, t, setLang }), [lang, t, setLang])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useT() {
  return useContext(Ctx)
}

/**
 * Depth for the language in hand: centimetres always, inches too in English.
 *
 * A tourist who reads "30 cm" has a number. "12 in" is the thing that decides
 * whether they drive into it.
 */
export function depthText(cm, lang) {
  if (cm == null) return null
  if (lang !== 'en') return `${cm} ซม.`
  const inches = Math.round(cm / 2.54)
  return `${cm} cm (${inches} in)`
}

/** Whether free text from a reporter should carry a "this is Thai" label. */
export function isThai(text) {
  return typeof text === 'string' && /[฀-๿]/.test(text)
}
