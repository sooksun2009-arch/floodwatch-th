import { useRef, useState } from 'react'
import {
  api, ApiError, LEVELS, SITUATIONS, VERDICTS, levelLabel, reportAge, safePhotoUrl,
  timeAgo,
} from '../api'

// One endpoint input: type a name, use GPS, or drop a pin on the map.
function EndpointInput({ id, label, badge, value, point, onChange, onPick, picking, onUseGps }) {
  const [gpsBusy, setGpsBusy] = useState(false)

  const useGps = () => {
    if (!navigator.geolocation) {
      onUseGps(null, 'เบราว์เซอร์นี้ไม่รองรับการระบุตำแหน่ง')
      return
    }
    setGpsBusy(true)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setGpsBusy(false)
        onUseGps({ lat: position.coords.latitude, lng: position.coords.longitude })
      },
      (error) => {
        setGpsBusy(false)
        const reason =
          error.code === error.PERMISSION_DENIED
            ? 'คุณปฏิเสธการเข้าถึงตำแหน่ง เปิดสิทธิ์ในเบราว์เซอร์แล้วลองใหม่'
            : 'ระบุตำแหน่งไม่สำเร็จ ลองพิมพ์ชื่อสถานที่แทน'
        onUseGps(null, reason)
      },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  return (
    <div>
      <label className="label" htmlFor={id}>
        <span
          className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold text-white"
          style={{ background: badge === 'A' ? '#0ea5e9' : '#f43f5e' }}
        >
          {badge}
        </span>
        {label}
      </label>
      <div className="flex gap-2">
        <input
          id={id}
          className="field"
          value={value}
          placeholder={badge === 'A' ? 'เช่น บางนา, ถนนรามคำแหง' : 'เช่น ลาดพร้าว, จตุจักร'}
          onChange={(event) => onChange(event.target.value)}
          autoComplete="off"
        />
        <button
          type="button"
          onClick={useGps}
          disabled={gpsBusy}
          className="btn-ghost shrink-0 px-3 text-sm"
          title="ใช้ตำแหน่งปัจจุบันของฉัน"
        >
          {gpsBusy ? '…' : '📍'}
        </button>
        <button
          type="button"
          onClick={onPick}
          className={`shrink-0 rounded-xl border px-3 text-sm transition-colors ${
            picking
              ? 'border-sky-500 bg-sky-500/20 text-sky-200'
              : 'border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800'
          }`}
          title="ปักหมุดบนแผนที่"
        >
          {picking ? 'แตะแผนที่' : '🗺'}
        </button>
      </div>
      {point && (
        <p className="mt-1 text-xs text-slate-500">
          พิกัด {point.lat.toFixed(5)}, {point.lng.toFixed(5)}
        </p>
      )}
    </div>
  )
}

function HowTo({ onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 sm:items-center sm:p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="card max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-b-none sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="วิธีใช้งาน"
      >
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <h3 className="text-base font-bold">วิธีการใช้งาน</h3>
          <button
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-2xl leading-none text-slate-400 hover:bg-slate-800"
            aria-label="ปิด"
          >
            ×
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm leading-relaxed text-slate-300">
          <section>
            <h4 className="font-semibold text-slate-100">1. บอกว่าจะไปไหน</h4>
            <p className="mt-1">
              พิมพ์ชื่อถนน เขต หรือจังหวัดในช่อง <strong>ต้นทาง</strong> และ{' '}
              <strong>ปลายทาง</strong> เช่น &ldquo;บางนา&rdquo; หรือ &ldquo;ถนนรามคำแหง&rdquo;
            </p>
            <ul className="mt-2 space-y-1 text-slate-400">
              <li>📍 ใช้ตำแหน่งปัจจุบันของคุณ (ต้องอนุญาตการเข้าถึงตำแหน่ง)</li>
              <li>🗺 ปักหมุดเองบนแผนที่ แม่นที่สุดถ้าชื่อสถานที่ไม่ชัด</li>
              <li>⇅ สลับต้นทางกับปลายทาง สำหรับเช็คขากลับ</li>
            </ul>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">2. อ่านคำตัดสิน</h4>
            <div className="mt-2 space-y-1.5">
              {Object.entries(VERDICTS).map(([key, v]) => (
                <div key={key} className="flex items-center gap-2">
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-xs font-bold text-white ${v.tone}`}
                  >
                    {v.icon}
                  </span>
                  <span>{v.label}</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">3. ตรวจหลักฐาน 3 ชั้น</h4>
            <ol className="mt-1 space-y-1 text-slate-400">
              <li>
                <strong className="text-slate-300">กล้อง CCTV</strong> — เรียงตามกิโลเมตรของเส้นทาง
                กดดูภาพจริงก่อนออกรถ เชื่อถือได้ที่สุดเพราะเห็นกับตา
              </li>
              <li>
                <strong className="text-slate-300">รายงานจากผู้ใช้</strong> — บอกว่าจะเจอที่ กม.
                ไหน ลึกเท่าไหร่ มีคนยืนยันกี่ราย กดยืนยันหรือแย้งได้
              </li>
              <li>
                <strong className="text-slate-300">คลองใกล้เส้นทาง</strong> — ระดับน้ำจากเครื่องวัด
                ของหน่วยงาน คลองล้นตลิ่งมักทำให้ถนนท่วมตามในเวลาไม่นาน
              </li>
            </ol>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">4. ถามเป็นภาษาพูดก็ได้</h4>
            <p className="mt-1">
              กดปุ่ม <strong>ถาม AI</strong> มุมขวาล่าง แล้วพิมพ์ได้เลย เช่น
            </p>
            <ul className="mt-1 space-y-0.5 text-slate-400">
              <li>&ldquo;จากบางนาไปรามคำแหง ท่วมไหม&rdquo;</li>
              <li>&ldquo;น้ำ 40 ซม. ขับผ่านได้ไหม&rdquo;</li>
              <li>&ldquo;ตอนนี้ท่วมหนักที่ไหน&rdquo;</li>
            </ul>
          </section>

          <section className="rounded-xl border border-amber-900/60 bg-amber-950/30 p-3">
            <h4 className="font-semibold text-amber-200">ข้อจำกัดที่ต้องรู้</h4>
            <p className="mt-1 text-amber-100/80">
              แอปนี้ทำโดยบุคคลทั่วไป <strong>ไม่ใช่หน่วยงานราชการ</strong>{' '}
              และ<strong>ไม่ใช่ช่องทางขอความช่วยเหลือ</strong> ถ้าติดอยู่ในน้ำหรือต้องการ
              ความช่วยเหลือ โทร <a href="tel:1784" className="underline">1784</a> (ปภ.)
              หรือ <a href="tel:1555" className="underline">1555</a> ในกรุงเทพฯ
            </p>
            <p className="mt-2 text-amber-100/80">
              ระบบเห็นเฉพาะจุดที่มีผู้แจ้งหรือหน่วยงานรายงาน ไม่ใช่ทุกถนน
              &ldquo;ไปได้&rdquo; แปลว่ายังไม่มีใครแจ้ง ไม่ใช่การยืนยันว่าถนนแห้ง
              ตรวจกับภาพกล้องก่อนตัดสินใจเสมอ
            </p>
            <p className="mt-2 text-amber-100/80">
              ถ้าเจอน้ำลึกกว่าที่คาดระหว่างทาง ให้กลับรถ อย่าฝืนขับต่อ
            </p>
          </section>
        </div>

        <div className="sticky bottom-0 border-t border-slate-800 bg-slate-900/95 p-4 backdrop-blur">
          <button onClick={onClose} className="btn-primary w-full">
            เข้าใจแล้ว
          </button>
        </div>
      </div>
    </div>
  )
}

function CameraStrip({ cameras, onOpen }) {
  if (!cameras?.length) {
    return (
      <div className="card p-4">
        <h3 className="mb-1 text-sm font-bold text-slate-200">1. กล้อง CCTV ตามเส้นทาง</h3>
        <p className="text-sm text-slate-400">
          ยังไม่มีกล้องในระบบ — ระบบจะแสดงเฉพาะกล้องจริงของหน่วยงานเท่านั้น
          ผู้ดูแลเพิ่มได้ที่หน้าผู้ดูแล → จัดการกล้อง
        </p>
      </div>
    )
  }
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-bold text-slate-200">
          1. ดูด้วยตาตัวเอง — กล้องตามเส้นทาง ({cameras.length})
        </h3>
        <span className="text-xs text-slate-500">เรียงตามระยะทาง</span>
      </div>
      <div className="-mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-2">
        {cameras.map(({ camera, along_km, distance_from_route_m }) => (
          <button
            key={camera.id}
            onClick={() => onOpen(camera.id)}
            className="w-44 shrink-0 snap-start rounded-xl border border-slate-700 bg-slate-900 p-3 text-left transition-colors hover:border-sky-600 hover:bg-slate-800"
          >
            <div className="mb-1 flex items-center gap-1.5">
              <span className="text-base">📹</span>
              <span className="text-xs font-semibold text-sky-400">กม. {along_km.toFixed(1)}</span>
            </div>
            <p className="line-clamp-2 text-sm font-medium leading-snug text-slate-100">
              {camera.name}
            </p>
            <p className="mt-1 text-xs text-slate-500">ห่างเส้นทาง {distance_from_route_m} ม.</p>
            {camera.is_demo && <p className="mt-1 text-xs text-amber-400">สตรีมตัวอย่าง</p>}
            {camera.frame_age_minutes > 90 && (
              <p className="mt-1 text-xs text-amber-400">
                ภาพค้าง {timeAgo(camera.frame_age_minutes)}
              </p>
            )}
            {camera.nearby_flood_level && (
              <p className="mt-1 text-xs text-red-400">
                ใกล้จุด{LEVELS[camera.nearby_flood_level]?.short || ''}
              </p>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

function StationList({ stations }) {
  if (!stations?.length) return null
  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-slate-200">
        3. คลองใกล้เส้นทางที่ล้นตลิ่ง ({stations.length})
      </h3>
      <ul className="space-y-2">
        {stations.map(({ station, along_km, distance_from_route_m }) => (
          <li key={station.id} className="card p-3">
            <div className="flex items-start gap-3">
              <div className="flex w-14 shrink-0 flex-col items-center">
                <span className="text-xs font-bold text-slate-400">กม.</span>
                <span
                  className="text-lg font-bold leading-none"
                  style={{ color: SITUATIONS[station.situation_level]?.color || '#dc2626' }}
                >
                  {along_km.toFixed(1)}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-semibold leading-snug text-slate-100">{station.name}</p>
                <p
                  className="mt-0.5 text-sm font-medium"
                  style={{ color: SITUATIONS[station.situation_level]?.color || '#dc2626' }}
                >
                  สูงกว่าตลิ่ง {Number(station.diff_from_bank ?? 0).toFixed(2)} ม.
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span>ห่างเส้นทาง {distance_from_route_m} ม.</span>
                  {station.agency && <span>ข้อมูลโดย {station.agency}</span>}
                  {station.is_stale && <span className="text-amber-400">ข้อมูลไม่อัปเดต</span>}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-2 px-1 text-xs text-slate-500">
        เป็นระดับน้ำในคลองที่วัดด้วยเครื่องมือ ไม่ใช่ระดับน้ำบนถนน
        แต่คลองที่ล้นตลิ่งมักทำให้ถนนใกล้เคียงท่วมตามในเวลาไม่นาน
      </p>
    </div>
  )
}

function ObstacleList({ obstacles, onVote, votedIds }) {
  if (!obstacles?.length) {
    return (
      <div className="card border-emerald-800/50 bg-emerald-950/30 p-4">
        <p className="text-sm text-emerald-200">
          ไม่มีรายงานน้ำท่วมบนเส้นทางนี้
        </p>
        <p className="mt-1 text-xs text-emerald-300/70">
          หมายถึงยังไม่มีใครแจ้ง ไม่ใช่การยืนยันว่าถนนแห้ง — ถ้าคุณขับผ่านแล้วเจอน้ำ ช่วยกดแจ้งด้วยครับ
        </p>
      </div>
    )
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-slate-200">
        2. รายงานจากผู้ใช้บนเส้นทาง ({obstacles.length})
      </h3>
      <ul className="space-y-2">
        {obstacles.map(({ report, along_km, distance_from_route_m }) => {
          const color = LEVELS[report.level]?.color || '#64748b'
          const voted = votedIds.has(report.id)
          return (
            <li key={report.id} className="card p-3">
              <div className="flex items-start gap-3">
                <div className="flex w-14 shrink-0 flex-col items-center">
                  <span className="text-xs font-bold text-slate-400">กม.</span>
                  <span className="text-lg font-bold leading-none" style={{ color }}>
                    {along_km.toFixed(1)}
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold leading-snug text-slate-100">
                    {report.place || report.district || 'ไม่ระบุจุด'}
                  </p>
                  <p className="mt-0.5 text-sm font-medium" style={{ color }}>
                    {report.level_label || levelLabel(report.level)}
                    {report.depth_cm ? ` · วัดได้ ${report.depth_cm} ซม.` : ''}
                  </p>
                  {/* Right under the level, and coloured: on a road that can
                      change within the hour, the age is what says whether the
                      line above it is still true. */}
                  {(() => {
                    const age = reportAge(report.age_minutes)
                    if (!age) return null
                    return (
                      <p className="mt-0.5 text-sm font-semibold" style={{ color: age.color }}>
                        {age.text}
                        {age.note && (
                          <span className="ml-1 text-xs font-normal opacity-85">
                            · {age.note}
                          </span>
                        )}
                      </p>
                    )
                  })()}
                  {report.description && (
                    <p className="mt-1 text-sm leading-relaxed text-slate-400">
                      {report.description}
                    </p>
                  )}
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span>ห่างเส้นทาง {distance_from_route_m} ม.</span>
                    <span>ยืนยัน {report.confirm_count} · แย้ง {report.dispute_count}</span>
                    {report.source === 'official' && (
                      <span className="chip bg-sky-500/15 text-sky-300">ข้อมูลทางการ</span>
                    )}
                  </div>
                  {safePhotoUrl(report.photo_url) && (
                    <img
                      src={safePhotoUrl(report.photo_url)}
                      alt="ภาพจุดน้ำท่วม"
                      loading="lazy"
                      className="mt-2 max-h-44 rounded-lg object-cover"
                    />
                  )}
                  <div className="mt-2 flex gap-2">
                    <button
                      className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                      onClick={() => onVote(report.id, 'confirm')}
                      disabled={voted}
                    >
                      ยังท่วมอยู่
                    </button>
                    <button
                      className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                      onClick={() => onVote(report.id, 'dispute')}
                      disabled={voted}
                    >
                      น้ำลดแล้ว
                    </button>
                    {voted && <span className="self-center text-xs text-emerald-400">ขอบคุณครับ</span>}
                  </div>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default function RoutePanel({
  origin,
  destination,
  originText,
  destinationText,
  setOriginText,
  setDestinationText,
  setOrigin,
  setDestination,
  picking,
  setPicking,
  result,
  setResult,
  onOpenCamera,
  onAskChat,
  onReportHere,
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showHelp, setShowHelp] = useState(false)
  const [activeRoute, setActiveRoute] = useState(0)
  const [votedIds, setVotedIds] = useState(new Set())
  const abortRef = useRef(null)

  const hasAnything = Boolean(originText || destinationText || origin || destination || result)

  const clearAll = () => {
    // Cancel any check still in flight, or its result would land on the form
    // the user just cleared.
    abortRef.current?.abort()
    setOriginText('')
    setDestinationText('')
    setOrigin(null)
    setDestination(null)
    setResult(null)
    setPicking(null)
    setError(null)
    setVotedIds(new Set())
    setActiveRoute(0)
  }

  const swap = () => {
    setOriginText(destinationText)
    setDestinationText(originText)
    setOrigin(destination)
    setDestination(origin)
  }

  const check = async () => {
    setError(null)
    if (!origin && !originText.trim()) return setError('กรุณาระบุต้นทาง')
    if (!destination && !destinationText.trim()) return setError('กรุณาระบุปลายทาง')

    // Cancel a check still in flight so a fast second submit cannot have its
    // result overwritten by the slower first one.
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setBusy(true)
    try {
      const payload = { alternatives: true }
      if (origin) payload.origin = origin
      else payload.origin_text = originText.trim()
      if (destination) payload.destination = destination
      else payload.destination_text = destinationText.trim()

      const data = await api.checkRoute(payload, controller.signal)
      setResult(data)
      setActiveRoute(0)
      setVotedIds(new Set())
      if (!origin) setOrigin(data.origin)
      if (!destination) setDestination(data.destination)
      if (data.origin_label && !originText) setOriginText(data.origin_label)
      if (data.destination_label && !destinationText) setDestinationText(data.destination_label)
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err instanceof ApiError ? err.message : 'ตรวจเส้นทางไม่สำเร็จ ลองใหม่อีกครั้ง')
    } finally {
      setBusy(false)
    }
  }

  const vote = async (reportId, choice) => {
    try {
      await api.voteReport(reportId, choice)
      setVotedIds((previous) => new Set(previous).add(reportId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ส่งความเห็นไม่สำเร็จ')
    }
  }

  const route = result?.routes?.[activeRoute]
  const verdict = VERDICTS[route?.verdict || result?.verdict] || VERDICTS.clear

  return (
    <div className="space-y-4">
      {showHelp && <HowTo onClose={() => setShowHelp(false)} />}

      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-base font-bold">จะไปไหน เช็คก่อนออกรถ</h2>
          <div className="flex shrink-0 items-center gap-1">
            {hasAnything && (
              <button
                type="button"
                onClick={clearAll}
                className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:bg-slate-800"
              >
                ล้างค่า
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowHelp(true)}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 py-1 pl-1.5 pr-2.5 text-xs text-slate-300 transition-colors hover:bg-slate-800"
              title="วิธีการใช้งาน"
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-600 text-[11px] font-bold">
                i
              </span>
              วิธีการใช้งาน
            </button>
          </div>
        </div>
        <div className="space-y-3">
          <EndpointInput
            id="origin"
            label="ต้นทาง"
            badge="A"
            value={originText}
            point={origin}
            picking={picking === 'origin'}
            onChange={(value) => {
              setOriginText(value)
              setOrigin(null) // typing replaces a pin
            }}
            onPick={() => setPicking(picking === 'origin' ? null : 'origin')}
            onUseGps={(point, message) => {
              if (point) {
                setOrigin(point)
                setOriginText('ตำแหน่งของฉัน')
              } else setError(message)
            }}
          />

          <div className="flex justify-center">
            <button
              type="button"
              onClick={swap}
              className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800"
              title="สลับต้นทางกับปลายทาง"
            >
              ⇅ สลับ
            </button>
          </div>

          <EndpointInput
            id="destination"
            label="ปลายทาง"
            badge="B"
            value={destinationText}
            point={destination}
            picking={picking === 'destination'}
            onChange={(value) => {
              setDestinationText(value)
              setDestination(null)
            }}
            onPick={() => setPicking(picking === 'destination' ? null : 'destination')}
            onUseGps={(point, message) => {
              if (point) {
                setDestination(point)
                setDestinationText('ตำแหน่งของฉัน')
              } else setError(message)
            }}
          />
        </div>

        <button onClick={check} disabled={busy} className="btn-primary mt-4 w-full">
          {busy ? 'กำลังตรวจเส้นทาง…' : 'เช็คเส้นทางนี้'}
        </button>

        {error && (
          <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}
      </div>

      {result && (
        <>
          <div className={`card p-4 ring-1 ${verdict.ring}`}>
            <div className="flex items-start gap-3">
              <span
                className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-xl font-bold text-white ${verdict.tone}`}
              >
                {verdict.icon}
              </span>
              <div className="min-w-0">
                <p className="text-lg font-bold">{verdict.label}</p>
                <p className="text-sm text-slate-300">
                  {route?.verdict_label || result.verdict_label}
                </p>
                <p className="mt-1 text-sm text-slate-400">
                  {route?.distance_km} กม. · ประมาณ {Math.round(route?.duration_min || 0)} นาที
                </p>
              </div>
            </div>

            {result.recommendation && (
              <p className="mt-3 rounded-xl border border-sky-800 bg-sky-950/40 px-3 py-2 text-sm text-sky-200">
                {result.recommendation}
              </p>
            )}
            {result.degraded && (
              <p className="mt-3 rounded-xl border border-amber-800 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
                {result.degraded} — ผลเป็นการประมาณ ควรตรวจกล้องประกอบ
              </p>
            )}

            {result.routes.length > 1 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {result.routes.map((option, index) => {
                  const tone = VERDICTS[option.verdict] || VERDICTS.clear
                  return (
                    <button
                      key={option.label}
                      onClick={() => setActiveRoute(index)}
                      className={`rounded-xl border px-3 py-2 text-left text-xs transition-colors ${
                        index === activeRoute
                          ? 'border-sky-500 bg-sky-500/10'
                          : 'border-slate-700 hover:bg-slate-800'
                      }`}
                    >
                      <span className="block font-semibold text-slate-100">
                        {option.label}
                        {option.is_recommended && ' ★'}
                      </span>
                      <span className="text-slate-400">
                        {option.distance_km} กม. · {tone.label}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <CameraStrip cameras={route?.cameras} onOpen={onOpenCamera} />
          <ObstacleList obstacles={route?.obstacles} onVote={vote} votedIds={votedIds} />
          <StationList stations={route?.stations} />

          <div className="flex flex-wrap gap-2">
            <button
              className="btn-ghost text-sm"
              onClick={() =>
                onAskChat(
                  `มีทางเลี่ยงจาก${originText || 'ต้นทาง'}ไป${destinationText || 'ปลายทาง'}ไหม`,
                )
              }
            >
              ถามแชทบอทเรื่องทางเลี่ยง
            </button>
            <button className="btn-danger text-sm" onClick={onReportHere}>
              แจ้งน้ำท่วมจุดใหม่
            </button>
          </div>

          <details className="card p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-300">
              สรุปแบบข้อความ (คัดลอกส่งต่อได้)
            </summary>
            <pre className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
              {result.advice}
            </pre>
          </details>
        </>
      )}
    </div>
  )
}
