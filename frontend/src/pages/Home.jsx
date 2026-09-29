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
import SurveyCard from '../components/SurveyCard'
import AreaCard from '../components/AreaCard'
import { useT } from '../i18n'
import { FLOOD_ROAD_BANDS } from '../floodRoads'

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

  // One line, and the live count is the part that had to survive the move to
  // "how to use": a radar over a dry country draws nothing, which looks
  // exactly like a radar that is broken. The count says which, and the time it
  // was measured says whether to believe it. The explanation of what rain does
  // and does not mean is in the instructions now.
  return (
    <span title={detail || undefined}>
      {headline}
    </span>
  )
}

function SafetyNotice() {
  const { t } = useT()
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
        <span dangerouslySetInnerHTML={{ __html: t('safety.body') }} />
      </span>
      {/* Wraps between its pieces, never inside one. This was a single
          nowrap line 455px wide, which on a 390px phone widened the whole
          page to 481px: the browser zoomed everything out to fit, and every
          later pinch fought that. Each phrase still stays in one piece. */}
      <span className="ml-auto flex min-w-0 max-w-full flex-wrap items-center gap-x-1.5 gap-y-1 [&>*]:whitespace-nowrap">
        <span className="text-amber-200/70">{t('safety.urgent')}</span>
        <a
          href="tel:1784"
          className="rounded-lg bg-amber-600 px-2 py-0.5 font-semibold text-white hover:bg-amber-500"
        >
          {t('safety.call')}
        </a>
        <span className="text-amber-200/70">{t('safety.bkk')}</span>
        <a href="tel:1555" className="font-semibold text-amber-200 underline">
          1555
        </a>
        {/* This app says on the same line that it cannot summon help, which
            leaves someone who does need help with nowhere to go. Rodnam is a
            separate civilian platform with agencies signed up to answer, so
            handing them over is more use than ending the sentence.

            Inside this group rather than on a line of its own: a second row
            made the notice taller, pushed the map down, and put the chat
            button back over the OpenStreetMap credit. The phone numbers stay
            first -- a line that is always answered beats a form. */}
        <span className="text-amber-200/70">· {t('safety.needHelp')}</span>
        <a
          href="https://rodnam.zenture.co/"
          target="_blank"
          rel="noopener noreferrer"
          title={t('safety.rodnamTitle')}
          className="font-semibold text-amber-200 underline decoration-amber-700 underline-offset-2 hover:text-amber-100"
        >
          {t('safety.rodnam')} ↗
        </a>
      </span>
    </div>
  )
}

function Legend({ selected, onToggle, onReset, hasCameras, showRoads }) {
  const { t } = useT()
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
            <p className="font-semibold text-slate-300">{t('legend.title')}</p>
            <button
              onClick={() => setOpen(false)}
              className="rounded px-1 text-sm leading-none text-slate-500 hover:text-slate-200"
              aria-label={t('legend.collapse')}
            >
              −
            </button>
          </div>
          <ul className="space-y-0.5">
            {[
              // Short labels from the dictionary, not from LEVELS: that constant
              // is Thai, and the legend is the first thing a visitor reads.
              ...Object.entries(LEVELS).map(([key, value]) => [key, t(`level.${key}.short`), value.color]),
              // Only when there are cameras to see. The app has none of its
              // own, so this row was a colour with nothing behind it —
              // a legend entry for a layer that is always empty teaches
              // people that the legend does not mean anything.
              ...(hasCameras ? [['cameras', t('legend.cameras'), '#0ea5e9']] : []),
              ['stations', t('legend.gauges'), SITUATIONS[5].color],
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
          {showRoads && (
            <div className="mt-2 border-t border-slate-800 pt-1.5">
              <p className="mb-1 font-semibold text-slate-400">{t('legend.roads')}</p>
              <ul className="grid grid-cols-2 gap-x-2 gap-y-0.5">
                {FLOOD_ROAD_BANDS.map(([key, color]) => (
                  <li key={key} className="flex items-center gap-1.5 text-slate-300">
                    <span className="h-1 w-4 shrink-0 rounded-full" style={{ background: color }} />
                    <span>{t(`legend.road.${key}`)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[10px] leading-snug text-slate-500">{t('legend.roadsNote')}</p>
            </div>
          )}
          {selected.size > 0 && (
            <button
              onClick={onReset}
              className="mt-1.5 w-full rounded px-1 py-0.5 text-left text-[11px] text-sky-400 hover:bg-slate-800"
            >
              {t('legend.filtering')} {selected.size} · {t('legend.showAll')}
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
          {t('legend.chip')}
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
  // A second, narrower pick mode: instead of tapping anywhere on the map,
  // this one only ever responds to tapping an existing flood pin, and skips
  // straight to filing a dispute vote -- the same vote the popup's own
  // "น้ำลดแล้ว" button files, just reachable without first discovering that
  // popups have it. Mutually exclusive with `picking` below: turning one on
  // turns the other off, so the crosshair and the pin-tap hint are never
  // both trying to explain the map at once.
  const [subsideMode, setSubsideMode] = useState(false)
  const [mapCenter, setMapCenter] = useState(null)
  const { t } = useT()
  const [radarOn, setRadarOn] = useState(false)
  const [floodLayerOn, setFloodLayerOn] = useState(false)
  // On by default: this is road-level evidence, the thing the route verdict
  // most needed, and it only loads when the map is over the area it covers.
  const [roadsOn, setRoadsOn] = useState(true)
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
  const [focus, setFocus] = useState(null)
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
      setLoadError(t('map.loadFailed'))
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

  // `picking` can also be set from inside RoutePanel (the origin/destination
  // "pick on map" buttons call the setter directly), so this is the one place
  // that can reliably say "anyone entering that mode exits this one".
  useEffect(() => {
    if (picking) setSubsideMode(false)
  }, [picking])

  const onSubsideResult = useCallback((status) => {
    // Single-shot, like the other pick modes: one tap and it is done, rather
    // than staying armed and risking a second accidental vote on the next tap.
    setSubsideMode(false)
  }, [])

  const PICK_LABEL = {
    origin: t('route.from'), destination: t('route.to'), report: t('report.where'),
  }

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
        {/* A fixed 2.25rem row on wide screens (details open as a dropdown),
            which is exactly what the map height below subtracts for it. */}
        <AreaCard onFocus={setFocus} />
        {/* Taller on a phone than it was. A user reported being able to spread
              to zoom in but not pinch to zoom out: a pinch starts with the
              fingers apart, and in a 46vh box one of them lands outside the
              map, so MapLibre sees a single touch and pans instead. More room
              is also what makes dropping a pin on the right spot possible. */}
          <div className="relative h-[60vh] min-h-[22rem] overflow-hidden rounded-2xl border border-slate-800 lg:sticky lg:top-20 lg:h-[calc(100vh-10.75rem)]">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {t('map.loading')}
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
          showFloodRoads={roadsOn}
              selected={selected}
              onError={setMapError}
              pickMode={Boolean(picking)}
              subsideMode={subsideMode}
              onSubsideResult={onSubsideResult}
              fitKey={fitKey}
              focus={focus}
            />
          </Suspense>
          <Legend
            selected={selected}
            onToggle={toggleCategory}
            onReset={() => setSelected(new Set())}
            hasCameras={cameras.length > 0}
            showRoads={roadsOn}
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
                {t('pick.instruction', { what: PICK_LABEL[picking] })}
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
                  {t('common.cancel')}
                </button>
                <button
                  onClick={() => usePoint(mapCenter)}
                  disabled={!mapCenter}
                  className="flex-1 rounded-xl bg-sky-600 py-3 text-sm font-semibold text-white shadow-lg hover:bg-sky-500 disabled:opacity-50"
                >
                  {t('pick.confirm')}
                </button>
              </div>
            </>
          )}
          {/* One column for every optional layer control and its caption.
              Four separately positioned boxes in the same corner collided
              twice -- the satellite caption onto the legend, then onto the
              radar caption. Stacked, they cannot. The right inset clears the
              map's zoom controls. */}
          {!picking && (
            <div className="pointer-events-none absolute left-3 right-14 top-3 z-10 flex flex-col items-start gap-2 sm:right-auto sm:max-w-sm">
              <div className="pointer-events-auto flex flex-wrap gap-2">
                <button
                  onClick={() => setRoadsOn((on) => !on)}
                  aria-pressed={roadsOn}
                  className={`rounded-xl border px-3 py-2 text-sm backdrop-blur transition-colors ${
                    roadsOn
                      ? 'border-rose-500 bg-rose-950/90 text-rose-200'
                      : 'border-slate-700 bg-slate-950/85 text-slate-300 hover:bg-slate-900'
                  }`}
                >
                  🛣️ {t('layer.roads')}
                </button>
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
                    🌧️ {t('layer.radar')}
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
                    🛰️ {t('layer.satellite')}
                  </button>
                )}
              </div>
              {/* One line each, not a paragraph. The full explanation moved
                  into "how to use", because on a phone these covered most of
                  the map they were explaining. What stays is the part someone
                  has to see while the layer is on: these pictures are not a
                  statement about any road. */}
              {((rainEnabled && radarOn) || (floodLayer && floodLayerOn)) && (
                <div className="rounded-lg bg-slate-950/85 px-2.5 py-1 text-[11px] leading-snug text-slate-300 backdrop-blur">
                  {floodLayer && floodLayerOn && <div>{t('layer.satShort')}</div>}
                  {rainEnabled && radarOn && (
                    <div>
                      🌧️ <RadarCaption />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* The one control that only ever adds a hazard sat alone in this
              corner, and a reader said as much: it reads as the only thing
              this map lets you do. Stacked above it, same corner, is the
              other direction -- clearing one -- styled in the app's own
              "ปกติ" green rather than the hazard orange, so the two read as
              opposite actions rather than two flavours of the same button. */}
          {!picking && !subsideMode && (
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
              {t('report.button')}
            </button>
          )}
          {!picking && !subsideMode && (
            <button
              onClick={() => setSubsideMode(true)}
              className="absolute bottom-16 right-3 z-10 rounded-full border border-emerald-600 bg-emerald-950/90 px-4 py-2.5 text-sm font-semibold text-emerald-200 shadow-lg backdrop-blur hover:bg-emerald-900 lg:bottom-[9.25rem]"
            >
              {t('subside.button')}
            </button>
          )}
          {subsideMode && (
            <div className="absolute inset-x-3 top-3 z-10 flex items-start justify-between gap-2 rounded-xl border border-emerald-700 bg-emerald-950/95 px-3 py-2 text-sm text-emerald-100 backdrop-blur">
              <span>
                {reports.length > 0
                  ? t('subside.instruction')
                  : t('subside.instructionEmpty')}
              </span>
              <button
                onClick={() => setSubsideMode(false)}
                aria-label={t('common.cancel')}
                className="shrink-0 rounded-lg border border-emerald-700 px-2 py-1 text-xs text-emerald-200 hover:bg-emerald-900"
              >
                {t('common.cancel')}
              </button>
            </div>
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
          {t('byline.by')} <span className="font-semibold text-slate-300">Sooksun</span>
          {' · '}
          {t('byline.hire')}{' '}
          <a
            className="font-medium text-sky-400 underline decoration-sky-700 underline-offset-2 hover:text-sky-300"
            href="mailto:sooksun2009@gmail.com?subject=สนใจจ้างเขียนระบบ (จาก FloodWatch TH)"
          >
            sooksun2009@gmail.com
          </a>
        </p>

        <details className="card mt-4 p-4 text-xs leading-relaxed text-slate-400">
          <summary className="cursor-pointer font-semibold text-slate-300">
            {t('route.disclosure')}
          </summary>

          <p className="mt-3 font-semibold text-slate-300">{t('disc.limits')}</p>
          <p className="mt-1">
            <span dangerouslySetInnerHTML={{ __html: t('disc.limitsBody') }} />
          </p>

          <p className="mt-3 font-semibold text-slate-300">{t('disc.sources')}</p>
          <ul className="mt-1 space-y-0.5">
            <li>{t('disc.src1')}</li>
            <li>{t('disc.src2')}</li>
            <li>{t('disc.src3')}</li>
            <li>
              • {t('disc.basemap')}{' '}
              <a
                className="text-sky-400 hover:underline"
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noreferrer"
              >
                {t('map.attribution')}
              </a>
              , OSRM / OpenRouteService
            </li>
          </ul>

          <p className="mt-3 font-semibold text-slate-300">{t('disc.privacy')}</p>
          <p className="mt-1">
            <span dangerouslySetInnerHTML={{ __html: t('disc.privacyBody') }} />
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

      <SurveyCard blocked={reportOpen || chatOpen || Boolean(picking) || subsideMode} />
    </div>
  )
}
