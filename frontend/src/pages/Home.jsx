import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { api, LEVELS, SITUATIONS } from '../api'
import RoutePanel from '../components/RoutePanel'

// MapLibre is the largest dependency in the app. Loading it separately lets the
// route form — the thing a driver actually needs first — paint immediately on a
// phone connection, with the map filling in a moment later.
const MapView = lazy(() => import('../components/MapView'))
import CameraModal from '../components/CameraModal'
import ChatWidget from '../components/ChatWidget'
import ReportModal from '../components/ReportModal'

function FloodExtentCaption({ product }) {
  // Without this the layer is a coloured blob people will read as "these roads
  // are closed". It is neither live nor about roads, and both have to be said
  // where the layer is, not in a page someone has to go and find.
  const span = { '1day': 'วันที่ผ่านมา', '3days': '3 วันที่ผ่านมา',
                 '7days': '7 วันที่ผ่านมา', '30days': '30 วันที่ผ่านมา' }[product]
    || 'ช่วงที่ผ่านมา'
  return (
    <div className="max-w-[24rem] rounded-xl border border-amber-800/60 bg-amber-950/90 px-3 py-2 text-xs leading-relaxed text-amber-100 backdrop-blur">
      พื้นที่สีส้มคือบริเวณที่<b>ดาวเทียมเห็นน้ำใน{span}</b> — ไม่ใช่ภาพสด
      และ<b>ไม่ได้แปลว่าถนนในนั้นผ่านไม่ได้</b> ถนนยกสูงกลางทุ่งที่น้ำท่วมเป็นเรื่องปกติ
      <span className="mt-1 block text-amber-300/80">ข้อมูล GISTDA · ใช้ประกอบการตัดสินใจ ไม่ใช่คำยืนยัน</span>
    </div>
  )
}

function RadarCaption() {
  // Radar tiles are transparent where it is not raining, so a working radar
  // over a dry country looks exactly like a broken one. This says which it is,
  // using the camera feed — cameras with rain on them right now are
  // independent evidence that the rain data is live.
  const [state, setState] = useState({ loading: true })

  useEffect(() => {
    let alive = true
    api
      .rainCameras()
      .then((r) => alive && setState({ loading: false, data: r }))
      .catch(() => alive && setState({ loading: false, error: true }))
    return () => {
      alive = false
    }
  }, [])

  let headline = 'กำลังตรวจสภาพฝน…'
  let detail = null
  if (!state.loading) {
    if (state.error || state.data?.available === false) {
      headline = 'ตรวจสภาพฝนไม่ได้ตอนนี้'
    } else {
      const wet = state.data?.cameras?.length ?? 0
      const scanned = state.data?.scanned ?? 0
      // "ฝนตกที่กล้อง" was the data model talking, not a sentence anyone reads.
      // What these are is points around the country where rain is measured;
      // that they happen to be traffic cameras is a detail, kept in the small
      // print because it is what makes the number believable.
      headline = wet
        ? `ตอนนี้ฝนตกอยู่ ${wet} จาก ${scanned} จุดวัดทั่วประเทศ`
        : `ตอนนี้ไม่มีฝนเลย ทั้ง ${scanned} จุดวัดทั่วประเทศ`
      const at = state.data?.last_updated ? new Date(state.data.last_updated) : null
      detail = at && !Number.isNaN(at.getTime())
        ? `ข้อมูล ${at.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })} น. · จุดวัดคือกล้องจราจรสาธารณะ`
        : 'จุดวัดคือกล้องจราจรสาธารณะทั่วประเทศ'
    }
  }

  return (
    <div className="max-w-[16rem] rounded-xl border border-slate-700 bg-slate-950/90 px-2.5 py-1.5 text-xs text-slate-300 backdrop-blur">
      {headline}
      {detail && <span className="mt-0.5 block text-[11px] text-slate-500">{detail}</span>}
      <span className="mt-0.5 block text-[11px] text-slate-500">
        พื้นที่ที่ไม่มีสี = ไม่มีฝน
      </span>
    </div>
  )
}

function SafetyNotice() {
  // Permanent, not dismissible, and outside the map rather than floating over
  // it. Someone opening this during a flood needs to know two things before
  // they trust anything on the screen: nobody official stands behind it, and
  // it cannot summon help. A notice they can tap away is a notice that is gone
  // exactly when it matters.
  //
  // 1784 is the national disaster line; 1555 only answers for Bangkok, and
  // this map covers the whole country.
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-100/90">
      <span>
        แอปนี้ทำโดยบุคคลทั่วไป <strong className="text-amber-200">ไม่ใช่หน่วยงานราชการ</strong>{' '}
        และไม่ใช่ช่องทางขอความช่วยเหลือ
      </span>
      <span className="ml-auto flex items-center gap-1.5 whitespace-nowrap">
        <span className="text-amber-200/70">เหตุด่วน</span>
        <a
          href="tel:1784"
          className="rounded-lg bg-amber-600 px-2 py-0.5 font-semibold text-white hover:bg-amber-500"
        >
          โทร 1784
        </a>
        <span className="text-amber-200/70">ปภ. · ในกรุงเทพฯ</span>
        <a href="tel:1555" className="font-semibold text-amber-200 underline">
          1555
        </a>
      </span>
    </div>
  )
}

function Legend({ selected, onToggle, onReset }) {
  // On a phone the full key covers a third of the map and sits over marker
  // popups, so it starts collapsed there and expanded on a wider screen.
  const [open, setOpen] = useState(() => {
    try {
      return window.matchMedia('(min-width: 640px)').matches
    } catch {
      return false
    }
  })

  return (
    <div className="absolute bottom-3 left-3 z-10 max-w-[60vw]">
      {open ? (
        <div className="rounded-xl border border-slate-700 bg-slate-950/90 p-2.5 text-xs backdrop-blur">
          <div className="mb-1.5 flex items-center justify-between gap-3">
            <p className="font-semibold text-slate-300">ระดับน้ำ · กดเพื่อดูเฉพาะที่เลือก</p>
            <button
              onClick={() => setOpen(false)}
              className="rounded px-1 text-sm leading-none text-slate-500 hover:text-slate-200"
              aria-label="ย่อคำอธิบายสัญลักษณ์"
            >
              −
            </button>
          </div>
          <ul className="space-y-0.5">
            {[
              ...Object.entries(LEVELS).map(([key, value]) => [key, value.short, value.color]),
              ['cameras', 'กล้อง CCTV', '#0ea5e9'],
              ['stations', 'คลองเฝ้าระวัง/วิกฤติ', SITUATIONS[5].color],
            ].map(([key, label, color]) => {
              const picking = selected.size > 0
              const on = !picking || selected.has(key)
              return (
                <li key={key}>
                  <button
                    onClick={() => onToggle(key)}
                    aria-pressed={selected.has(key)}
                    className={`flex w-full items-center gap-2 rounded px-1 py-0.5 text-left transition-colors hover:bg-slate-800 ${
                      selected.has(key)
                        ? 'bg-slate-800 font-semibold text-white'
                        : on
                          ? 'text-slate-300'
                          : 'text-slate-600'
                    }`}
                  >
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-slate-900"
                      style={{ background: color, opacity: on ? 1 : 0.25 }}
                    />
                    <span>{label}</span>
                  </button>
                </li>
              )
            })}
          </ul>
          {selected.size > 0 && (
            <button
              onClick={onReset}
              className="mt-1.5 w-full rounded px-1 py-0.5 text-left text-[11px] text-sky-400 hover:bg-slate-800"
            >
              แสดงเฉพาะ {selected.size} ชนิด · กดเพื่อแสดงทั้งหมด
            </button>
          )}
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-950/90 py-1.5 pl-2 pr-3 text-xs text-slate-300 backdrop-blur"
        >
          {/* A row of the actual marker colours reads as a key even collapsed. */}
          <span className="flex -space-x-0.5">
            {['puddle', 'shallow', 'deep', 'severe'].map((key) => (
              <span
                key={key}
                className="h-2.5 w-2.5 rounded-full ring-1 ring-slate-950"
                style={{ background: LEVELS[key].color }}
              />
            ))}
          </span>
          สัญลักษณ์
        </button>
      )}
    </div>
  )
}

export default function Home() {
  const [reports, setReports] = useState([])
  const [cameras, setCameras] = useState([])
  const [stations, setStations] = useState([])
  const [result, setResult] = useState(null)

  const [originText, setOriginText] = useState('')
  const [destinationText, setDestinationText] = useState('')
  const [origin, setOrigin] = useState(null)
  const [destination, setDestination] = useState(null)
  const [picking, setPicking] = useState(null)
  const [mapCenter, setMapCenter] = useState(null)
  const [radarOn, setRadarOn] = useState(false)
  const [floodLayerOn, setFloodLayerOn] = useState(false)
  // Categories picked in the legend. Empty means no choice made, which shows
  // everything. Kept here rather than in MapView so the choice survives the
  // map being re-rendered.
  const [selected, setSelected] = useState(() => new Set())
  const toggleCategory = useCallback((key) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])
  // The radar button only appears where there is a radar. Asking the server
  // beats hardcoding it: the key lives there, not here.
  const [rainEnabled, setRainEnabled] = useState(false)
  const [floodLayer, setFloodLayer] = useState(null)

  const [activeCamera, setActiveCamera] = useState(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [pendingChat, setPendingChat] = useState(null)
  const [reportOpen, setReportOpen] = useState(false)
  const [reportPoint, setReportPoint] = useState(null)
  const [fitKey, setFitKey] = useState(0)
  const [loadError, setLoadError] = useState(null)
  const [mapError, setMapError] = useState(null)

  const loadData = useCallback(async () => {
    try {
      const [reportData, cameraData, stationData] = await Promise.all([
        api.reports({ limit: 500 }),
        api.cameras({ limit: 800 }),
        // Gauges the operators themselves flag as worth watching (เฝ้าระวัง
        // upwards) plus anything over its bank. Showing all ~1,100 would bury
        // the handful that matter.
        api.stations({ min_situation: 4, limit: 800 }),
      ])
      setReports(reportData.items || [])
      setCameras(cameraData || [])
      setStations(stationData || [])
      setLoadError(null)
    } catch {
      setLoadError('โหลดข้อมูลแผนที่ไม่สำเร็จ — ตรวจการเชื่อมต่อแล้วลองใหม่')
    }
  }, [])

  useEffect(() => {
    loadData()
    // Flood data goes stale fast; refresh while the tab is open, but only when
    // it is actually visible so a backgrounded tab stops polling.
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadData()
    }, 90_000)
    return () => clearInterval(timer)
  }, [loadData])

  const openCamera = useCallback(
    async (cameraId) => {
      // Usually already in the map's camera list; a chatbot answer can name one
      // outside the current viewport, so fall back to fetching it by id.
      const known = cameras.find((camera) => camera.id === cameraId)
      if (known) {
        setActiveCamera(known)
        return
      }
      try {
        const response = await fetch(`/api/cameras/${cameraId}`)
        if (response.ok) setActiveCamera(await response.json())
      } catch {
        /* offline: leave the modal closed rather than showing a broken player */
      }
    },
    [cameras],
  )

  const usePoint = useCallback(
    (point) => {
      if (!point) return
      const label = `หมุด ${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}`
      if (picking === 'origin') {
        setOrigin(point)
        setOriginText(label)
      } else if (picking === 'destination') {
        setDestination(point)
        setDestinationText(label)
      } else if (picking === 'report') {
        setReportPoint(point)
        setReportOpen(true)
      }
      setPicking(null)
    },
    [picking],
  )

  // Tapping the map still works, and on a desktop with a mouse it is the
  // quickest way. It is not offered as the only way, because on a phone a tap
  // lands on a pin or a route line far more often than on bare map.
  useEffect(() => {
    api.rainStatus().then((r) => setRainEnabled(Boolean(r?.enabled))).catch(() => {})
    // Absent key -> absent button. A control that is present and does nothing
    // is worse than no control.
    api.floodExtentStatus()
      .then((r) => setFloodLayer(r?.enabled ? r : null))
      .catch(() => {})
  }, [])

  const onMapClick = useCallback(
    (point) => {
      if (picking) usePoint(point)
    },
    [picking, usePoint],
  )

  const PICK_LABEL = { origin: 'ต้นทาง', destination: 'ปลายทาง', report: 'จุดที่น้ำท่วม' }

  const showRouteOnMap = useCallback((route) => {
    setResult(route)
    setOrigin(route.origin)
    setDestination(route.destination)
    setOriginText(route.origin_label || '')
    setDestinationText(route.destination_label || '')
    setChatOpen(false)
    setFitKey((key) => key + 1)
  }, [])

  useEffect(() => {
    if (result) setFitKey((key) => key + 1)
  }, [result])

  const routes = result?.routes || []

  return (
    <div className="mx-auto max-w-7xl gap-4 p-3 sm:p-4 lg:flex lg:items-start">
      <div className="lg:order-2 lg:flex-1">
        <SafetyNotice />
        <div className="relative h-[46vh] overflow-hidden rounded-2xl border border-slate-800 lg:sticky lg:top-20 lg:h-[calc(100vh-8.5rem)]">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                กำลังโหลดแผนที่…
              </div>
            }
          >
            <MapView
              className="h-full w-full"
              reports={reports}
              cameras={cameras}
              stations={stations}
              routes={routes}
              origin={origin}
              destination={destination}
              onCameraClick={openCamera}
              onMapClick={onMapClick}
              onCenterChange={setMapCenter}
              showRadar={radarOn}
          showFloodExtent={floodLayerOn}
              selected={selected}
              onError={setMapError}
              pickMode={Boolean(picking)}
              fitKey={fitKey}
            />
          </Suspense>
          <Legend
            selected={selected}
            onToggle={toggleCategory}
            onReset={() => setSelected(new Set())}
          />
          {mapError && (
            <div className="absolute inset-x-3 top-3 z-20 rounded-xl border border-red-800 bg-red-950/90 px-3 py-2 text-sm text-red-200 backdrop-blur">
              {mapError}
            </div>
          )}
          {picking && (
            <>
              {/* Pan the map under a fixed crosshair instead of tapping a
                  spot. A tap on a phone usually lands on a pin or a route
                  line, and then nothing happens and it looks broken — the
                  crosshair cannot be missed and needs no aim. */}
              <div
                className="pointer-events-none absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-full"
                aria-hidden="true"
              >
                <svg width="34" height="44" viewBox="0 0 34 44" fill="none">
                  <path
                    d="M17 43C17 43 31 26.5 31 16.5C31 8.8 24.7 2.5 17 2.5S3 8.8 3 16.5C3 26.5 17 43 17 43Z"
                    fill="#0ea5e9"
                    stroke="#e0f2fe"
                    strokeWidth="2.5"
                  />
                  <circle cx="17" cy="16.5" r="4.5" fill="#e0f2fe" />
                </svg>
              </div>
              <div className="absolute left-1/2 top-3 z-10 w-[min(92%,26rem)] -translate-x-1/2 rounded-xl border border-sky-700 bg-sky-950/95 px-3 py-2 text-center text-sm text-sky-100 backdrop-blur">
                เลื่อนแผนที่ให้หมุดอยู่ตรง{PICK_LABEL[picking]}
                {mapCenter && (
                  <span className="mt-0.5 block text-xs text-sky-300/80">
                    {mapCenter.lat.toFixed(5)}, {mapCenter.lng.toFixed(5)}
                  </span>
                )}
              </div>
              <div className="absolute inset-x-3 bottom-3 z-10 flex gap-2">
                <button
                  onClick={() => setPicking(null)}
                  className="rounded-xl border border-slate-600 bg-slate-900/95 px-4 py-3 text-sm text-slate-300 backdrop-blur hover:bg-slate-800"
                >
                  ยกเลิก
                </button>
                <button
                  onClick={() => usePoint(mapCenter)}
                  disabled={!mapCenter}
                  className="flex-1 rounded-xl bg-sky-600 py-3 text-sm font-semibold text-white shadow-lg hover:bg-sky-500 disabled:opacity-50"
                >
                  ยืนยันตำแหน่งนี้
                </button>
              </div>
            </>
          )}
          {/* One column for every optional layer control and its caption.
              Four separately positioned boxes in the same corner collided
              twice -- the satellite caption onto the legend, then onto the
              radar caption. Stacked, they cannot. The right inset clears the
              map's zoom controls. */}
          {!picking && (rainEnabled || floodLayer) && (
            <div className="pointer-events-none absolute left-3 right-14 top-3 z-10 flex flex-col items-start gap-2 sm:right-auto sm:max-w-sm">
              <div className="pointer-events-auto flex flex-wrap gap-2">
                {rainEnabled && (
                  <button
                    onClick={() => setRadarOn((on) => !on)}
                    aria-pressed={radarOn}
                    className={`rounded-xl border px-3 py-2 text-sm backdrop-blur transition-colors ${
                      radarOn
                        ? 'border-sky-500 bg-sky-950/90 text-sky-200'
                        : 'border-slate-700 bg-slate-950/85 text-slate-300 hover:bg-slate-900'
                    }`}
                  >
                    🌧️ เรดาร์ฝน
                  </button>
                )}
                {floodLayer && (
                  <button
                    onClick={() => setFloodLayerOn((on) => !on)}
                    aria-pressed={floodLayerOn}
                    className={`rounded-xl border px-3 py-2 text-sm backdrop-blur transition-colors ${
                      floodLayerOn
                        ? 'border-amber-500 bg-amber-950/90 text-amber-200'
                        : 'border-slate-700 bg-slate-950/85 text-slate-300 hover:bg-slate-900'
                    }`}
                  >
                    🛰️ น้ำท่วมจากดาวเทียม
                  </button>
                )}
              </div>
              {rainEnabled && radarOn && <RadarCaption />}
              {floodLayer && floodLayerOn && (
                <FloodExtentCaption product={floodLayer.product} />
              )}
            </div>
          )}
          {!picking && (
            <button
              onClick={() => {
                setReportPoint(null)
                setReportOpen(true)
              }}
              // Lifted on wide screens only: there the map reaches the bottom
              // of the window and this lands on top of the chat button, which
              // is fixed to the viewport. On a phone the map ends well above it.
              className="absolute bottom-3 right-3 z-10 rounded-full bg-orange-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-orange-950/50 hover:bg-orange-500 lg:bottom-24"
            >
              แจ้งน้ำท่วม
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 lg:order-1 lg:mt-0 lg:w-[26rem] lg:shrink-0">
        {loadError && (
          <p className="mb-3 rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {loadError}
          </p>
        )}
        <RoutePanel
          origin={origin}
          destination={destination}
          originText={originText}
          destinationText={destinationText}
          setOriginText={setOriginText}
          setDestinationText={setDestinationText}
          setOrigin={setOrigin}
          setDestination={setDestination}
          picking={picking}
          setPicking={setPicking}
          result={result}
          setResult={setResult}
          onOpenCamera={openCamera}
          onAskChat={(message) => setPendingChat(message)}
          onReportHere={() => {
            setReportPoint(null)
            setReportOpen(true)
          }}
        />

        {/* Outside the collapsible panel on purpose: someone who wants to
            ask about commissioning work should not have to open "sources and
            limitations" to find out a person made this. */}
        <p className="mt-4 px-1 text-xs text-slate-500">
          พัฒนาโดย <span className="font-semibold text-slate-300">Sooksun</span>
          {' · '}
          รับเขียนเว็บและระบบภายในองค์กร{' '}
          <a
            className="font-medium text-sky-400 underline decoration-sky-700 underline-offset-2 hover:text-sky-300"
            href="mailto:sooksun2009@gmail.com?subject=สนใจจ้างเขียนระบบ (จาก FloodWatch TH)"
          >
            sooksun2009@gmail.com
          </a>
        </p>

        <details className="card mt-4 p-4 text-xs leading-relaxed text-slate-400">
          <summary className="cursor-pointer font-semibold text-slate-300">
            แหล่งข้อมูล ข้อจำกัด และความเป็นส่วนตัว
          </summary>

          <p className="mt-3 font-semibold text-slate-300">ข้อจำกัดที่ต้องรู้</p>
          <p className="mt-1">
            ระบบครอบคลุม<strong>เฉพาะจุดที่มีผู้แจ้งหรือหน่วยงานรายงาน</strong> ไม่ใช่ทุกถนน
            การที่เส้นทางขึ้นว่า &ldquo;ไปได้&rdquo; แปลว่ายังไม่มีใครแจ้ง ไม่ใช่การยืนยันว่าถนนแห้ง
            ควรตรวจกับภาพกล้องก่อนตัดสินใจเสมอ ระบบนี้ไม่ใช่ประกาศทางการ
          </p>

          <p className="mt-3 font-semibold text-slate-300">แหล่งข้อมูล</p>
          <ul className="mt-1 space-y-0.5">
            <li>• รายงานจากผู้ใช้ทั่วไป ผ่านการตรวจสอบโดยผู้ดูแลก่อนขึ้นแผนที่</li>
            <li>• รายงานจากหน่วยงาน ที่ผู้ดูแลนำเข้าระบบ</li>
            <li>• ภาพกล้อง CCTV จากหน่วยงานเจ้าของกล้องแต่ละแห่ง (ระบุชื่อในหน้ากล้อง)</li>
            <li>
              • แผนที่และเส้นทาง:{' '}
              <a
                className="text-sky-400 hover:underline"
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noreferrer"
              >
                ผู้ร่วมสร้าง OpenStreetMap
              </a>
              , OSRM / OpenRouteService
            </li>
          </ul>

          <p className="mt-3 font-semibold text-slate-300">ความเป็นส่วนตัว</p>
          <p className="mt-1">
            ระบบ<strong>ไม่เก็บ</strong>ต้นทาง-ปลายทางที่คุณค้นหา และไม่เก็บประวัติการเดินทาง
            ตำแหน่ง GPS ใช้ในเบราว์เซอร์เพื่อคำนวณผลเท่านั้น รูปที่อัปโหลดจะถูกลบข้อมูล EXIF
            (รวมพิกัดกล้อง) ก่อนบันทึก ส่วนคำถามในแชทและหมายเลข IP ของผู้แจ้งจะถูกเก็บไว้
            เพื่อป้องกันการก่อกวนและปรับปรุงระบบเท่านั้น
          </p>
        </details>
      </div>

      <CameraModal
        camera={activeCamera}
        onClose={() => setActiveCamera(null)}
        onReportHere={(camera) => {
          setReportPoint({ lat: camera.lat, lng: camera.lng })
          setActiveCamera(null)
          setReportOpen(true)
        }}
      />

      <ReportModal
        open={reportOpen}
        initialPoint={reportPoint}
        onClose={() => setReportOpen(false)}
        onPickOnMap={() => {
          setReportOpen(false)
          setPicking('report')
        }}
        onSubmitted={loadData}
      />

      <ChatWidget
        open={chatOpen}
        setOpen={setChatOpen}
        pendingMessage={pendingChat}
        onConsumed={() => setPendingChat(null)}
        onShowRoute={showRouteOnMap}
        onOpenCamera={openCamera}
      />
    </div>
  )
}
