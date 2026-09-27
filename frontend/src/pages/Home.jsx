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

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-xl border border-slate-700 bg-slate-950/85 p-2.5 text-xs backdrop-blur">
      <p className="mb-1.5 font-semibold text-slate-300">ระดับน้ำ</p>
      <ul className="space-y-1">
        {Object.entries(LEVELS).map(([key, value]) => (
          <li key={key} className="flex items-center gap-2 text-slate-400">
            <span
              className="h-2.5 w-2.5 rounded-full ring-1 ring-slate-900"
              style={{ background: value.color }}
            />
            {value.short}
          </li>
        ))}
        <li className="flex items-center gap-2 pt-1 text-slate-400">
          <span className="h-2.5 w-2.5 rounded-full bg-sky-500 ring-2 ring-sky-100" />
          กล้อง CCTV
        </li>
        <li className="flex items-center gap-2 text-slate-400">
          <span
            className="h-2.5 w-2.5 rounded-full ring-1 ring-slate-900"
            style={{ background: SITUATIONS[5].color }}
          />
          คลองเฝ้าระวัง/วิกฤติ
        </li>
      </ul>
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

  const onMapClick = useCallback(
    (point) => {
      if (picking === 'origin') {
        setOrigin(point)
        setOriginText(`หมุด ${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}`)
        setPicking(null)
      } else if (picking === 'destination') {
        setDestination(point)
        setDestinationText(`หมุด ${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}`)
        setPicking(null)
      }
    },
    [picking],
  )

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
        <div className="relative h-[46vh] overflow-hidden rounded-2xl border border-slate-800 lg:sticky lg:top-20 lg:h-[calc(100vh-6rem)]">
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
              onError={setMapError}
              pickMode={Boolean(picking)}
              fitKey={fitKey}
            />
          </Suspense>
          <Legend />
          {mapError && (
            <div className="absolute inset-x-3 top-3 z-20 rounded-xl border border-red-800 bg-red-950/90 px-3 py-2 text-sm text-red-200 backdrop-blur">
              {mapError}
            </div>
          )}
          {picking && (
            <div className="absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-full border border-sky-600 bg-sky-950/90 px-3.5 py-1.5 text-sm text-sky-200 backdrop-blur">
              แตะบนแผนที่เพื่อปัก{picking === 'origin' ? 'ต้นทาง' : 'ปลายทาง'}
            </div>
          )}
          <button
            onClick={() => {
              setReportPoint(null)
              setReportOpen(true)
            }}
            className="absolute bottom-3 right-3 z-10 rounded-full bg-orange-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-orange-950/50 hover:bg-orange-500"
          >
            แจ้งน้ำท่วม
          </button>
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
