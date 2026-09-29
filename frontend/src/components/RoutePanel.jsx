import { useRef, useState } from 'react'
import {
  api, ApiError, LEVELS, SITUATIONS, VERDICTS, levelLabel, reportAge, safePhotoUrl,
  timeAgo,
} from '../api'
import { depthText, useT } from '../i18n'

// One endpoint input: type a name, use GPS, or drop a pin on the map.
function EndpointInput({ id, label, badge, value, point, onChange, onPick, picking, onUseGps }) {
  const { t, lang } = useT()
  const [gpsBusy, setGpsBusy] = useState(false)

  const useGps = () => {
    if (!navigator.geolocation) {
      onUseGps(null, t('rp.gpsUnsupported'))
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
            ? t('rp.gpsDenied')
            : t('rp.gpsFailed')
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
          placeholder={badge === 'A' ? t('route.fromPlaceholder') : t('route.toPlaceholder')}
          onChange={(event) => onChange(event.target.value)}
          autoComplete="off"
        />
        <button
          type="button"
          onClick={useGps}
          disabled={gpsBusy}
          className="btn-ghost shrink-0 px-3 text-sm"
          title={t('rp.useGps')}
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
          title={t('rp.pinOnMap')}
        >
          {picking ? t('rp.tapMap') : '🗺'}
        </button>
      </div>
      {point && (
        <p className="mt-1 text-xs text-slate-500">
          {t('rp.coords')} {point.lat.toFixed(5)}, {point.lng.toFixed(5)}
        </p>
      )}
    </div>
  )
}

function Rich({ html, className }) {
  return <p className={className} dangerouslySetInnerHTML={{ __html: html }} />
}

function HowTo({ onClose }) {
  const { t, lang } = useT()
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
        aria-label={t('route.how')}
      >
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <h3 className="text-base font-bold">{t('route.how')}</h3>
          <button
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-2xl leading-none text-slate-400 hover:bg-slate-800"
            aria-label={t('rp.close')}
          >
            ×
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm leading-relaxed text-slate-300">
          <section>
            <h4 className="font-semibold text-slate-100">{t('how.1')}</h4>
            <p className="mt-1">
              <span dangerouslySetInnerHTML={{ __html: t('how.1body') }} />
            </p>
            <ul className="mt-2 space-y-1 text-slate-400">
              <li>{t('how.1gps')}</li>
              <li>{t('how.1pin')}</li>
              <li>{t('how.1swap')}</li>
              <li>{t('how.1area')}</li>
            </ul>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">{t('how.2')}</h4>
            <div className="mt-2 space-y-1.5">
              {Object.entries(VERDICTS).map(([key, v]) => (
                <div key={key} className="flex items-center gap-2">
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-xs font-bold text-white ${v.tone}`}
                  >
                    {v.icon}
                  </span>
                  <span>{t(`verdict.${key}`)}</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">{t('how.3')}</h4>
            <ol className="mt-1 space-y-1 text-slate-400">
              <li>
                <span dangerouslySetInnerHTML={{ __html: t('how.3cam') }} />
              </li>
              <li>
                <span dangerouslySetInnerHTML={{ __html: t('how.3rep') }} />
              </li>
              <li>
                <span dangerouslySetInnerHTML={{ __html: t('how.3roads') }} />
              </li>
              <li>
                <span dangerouslySetInnerHTML={{ __html: t('how.3gauge') }} />
              </li>
            </ol>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">{t('how.4')}</h4>
            <p className="mt-1">
              <span dangerouslySetInnerHTML={{ __html: t('how.4body') }} />
            </p>
            <ul className="mt-1 space-y-0.5 text-slate-400">
              <li>{t('how.4a')}</li>
              <li>{t('how.4b')}</li>
              <li>{t('how.4c')}</li>
            </ul>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">{t('how.layers')}</h4>
            <ul className="mt-1 space-y-1.5 text-slate-400">
              <li dangerouslySetInnerHTML={{ __html: t('how.layersRoads') }} />
              <li dangerouslySetInnerHTML={{ __html: t('how.layersSat') }} />
              <li dangerouslySetInnerHTML={{ __html: t('how.layersRain') }} />
            </ul>
          </section>

          <section>
            <h4 className="font-semibold text-slate-100">{t('how.update')}</h4>
            <p className="mt-1" dangerouslySetInnerHTML={{ __html: t('how.updateReports') }} />
            <ul className="mt-1 space-y-1 text-slate-400">
              <li dangerouslySetInnerHTML={{ __html: t('how.updateSubside') }} />
              <li>{t('how.updateExpire')}</li>
              <li>{t('how.updateAdmin')}</li>
            </ul>
            <p className="mt-2" dangerouslySetInnerHTML={{ __html: t('how.updateRoads') }} />
            <p className="mt-2" dangerouslySetInnerHTML={{ __html: t('how.updateReport') }} />
          </section>

          <section>
            <p dangerouslySetInnerHTML={{ __html: t('how.shelters') }} />
          </section>

          <section className="rounded-xl border border-amber-900/60 bg-amber-950/30 p-3">
            <h4 className="font-semibold text-amber-200">{t('rp.limitsHeading')}</h4>
            <p className="mt-1 text-amber-100/80">
              <span dangerouslySetInnerHTML={{ __html: t('how.limits1') }} />
            </p>
            <p className="mt-2 text-amber-100/80">
              {t('how.limits2')}
            </p>
            <p className="mt-2 text-amber-100/80">
              {t('how.limits3')}
            </p>
          </section>
        </div>

        <div className="sticky bottom-0 border-t border-slate-800 bg-slate-900/95 p-4 backdrop-blur">
          <button onClick={onClose} className="btn-primary w-full">
            {t('rp.understood')}
          </button>
        </div>
      </div>
    </div>
  )
}

function CameraStrip({ cameras, onOpen }) {
  const { t, lang } = useT()
  if (!cameras?.length) {
    return (
      <div className="card p-4">
        <h3 className="mb-1 text-sm font-bold text-slate-200">{t('rp.camerasHeading')}</h3>
        <p className="text-sm text-slate-400">
          {t('rp.camerasNone')}
          ผู้ดูแลเพิ่มได้ที่หน้าผู้ดูแล → จัดการกล้อง
        </p>
      </div>
    )
  }
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-bold text-slate-200">
          {t('rp.camerasStep')} ({cameras.length})
        </h3>
        <span className="text-xs text-slate-500">{t('rp.sortedByDistance')}</span>
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
              <span className="text-xs font-semibold text-sky-400">{t('rp.kmMark')} {along_km.toFixed(1)}</span>
            </div>
            <p className="line-clamp-2 text-sm font-medium leading-snug text-slate-100">
              {camera.name}
            </p>
            <p className="mt-1 text-xs text-slate-500">{t('rp.offRoute')} {distance_from_route_m} {t('route.m')}</p>
            {camera.is_demo && <p className="mt-1 text-xs text-amber-400">{t('rp.demoStream')}</p>}
            {camera.frame_age_minutes > 90 && (
              <p className="mt-1 text-xs text-amber-400">
                {t('rp.frozenFrame')} {timeAgo(camera.frame_age_minutes, t)}
              </p>
            )}
            {camera.nearby_flood_level && (
              <p className="mt-1 text-xs text-red-400">
                {t('rp.nearFlood')} {t(`level.${camera.nearby_flood_level}.short`)}
              </p>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

const SEDAN_COLOR = { blocked: '#dc2626', risky: '#f97316', caution: '#f59e0b', ok: '#22c55e' }

/** Flooded stretches of road along the route, from Floodboard.
 *
 * The headline is what the verdict above actually counted, not what the feed
 * claimed. An unsure stretch used to shout "เสี่ยง" in orange and then admit
 * in smaller type that it had only been counted as "ระวัง" -- the same kind of
 * contradiction a reader already caught once, in the verdict box.
 */
function RoadList({ roads, attribution }) {
  const { t, lang } = useT()
  if (!roads?.length) return null
  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-slate-200">
        {t('rp.roadsStep')} ({roads.length})
      </h3>
      <ul className="space-y-2">
        {roads.map((road, i) => {
          const colour = road.confident ? SEDAN_COLOR[road.sedan] || '#f59e0b' : '#f59e0b'
          return (
          <li key={`${road.name}-${road.along_km}-${i}`} className={`card p-3 ${road.confident ? '' : 'opacity-75'}`}>
            <div className="flex items-start gap-3">
              <div className="flex w-14 shrink-0 flex-col items-center">
                <span className="text-xs font-bold text-slate-400">{t('rp.kmMark')}</span>
                <span className="text-lg font-bold leading-none" style={{ color: colour }}>
                  {road.along_km.toFixed(1)}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-semibold leading-snug text-slate-100">
                  {(lang === 'en' && road.name_en) || road.name || t('roads.unnamed')}
                </p>
                {road.confident ? (
                  <p className="mt-0.5 text-sm font-medium" style={{ color: colour }}>
                    {t('roads.sedan')}: {t(`roads.v.${road.sedan}`)}
                    {road.closed ? ` · ${t('roads.closed')}` : ''}
                    {road.depth_cm ? ` · ${t('roads.depth', { cm: Math.round(road.depth_cm) })}` : ''}
                  </p>
                ) : (
                  <p className="mt-0.5 text-sm font-medium" style={{ color: colour }}>
                    {t('roads.countedAs')}
                    {road.depth_cm ? ` · ${t('roads.depth', { cm: Math.round(road.depth_cm) })}` : ''}
                  </p>
                )}
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  {!road.confident && (
                    <span>
                      {t('roads.feedSays', {
                        v: `${t('roads.sedan')} ${t(`roads.v.${road.sedan}`)}`,
                      })}
                    </span>
                  )}
                  {road.confident && <span>{t('roads.moto')}: {t(`roads.v.${road.motorbike}`)}</span>}
                  <span>{t('roads.conf', { n: Math.round(road.conf * 100) })}</span>
                  {road.length_m > 0 && <span>{t('roads.length', { m: road.length_m })}</span>}
                </div>
              </div>
            </div>
          </li>
          )
        })}
      </ul>
      <p className="mt-2 px-1 text-xs text-slate-500">
        {attribution || t('roads.credit')} · {t('roads.panelNote')}
      </p>
    </div>
  )
}

function StationList({ stations }) {
  const { t, lang } = useT()
  if (!stations?.length) return null
  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-slate-200">
        {t('rp.gaugesStep')} ({stations.length})
      </h3>
      <ul className="space-y-2">
        {stations.map(({ station, along_km, distance_from_route_m }) => (
          <li key={station.id} className="card p-3">
            <div className="flex items-start gap-3">
              <div className="flex w-14 shrink-0 flex-col items-center">
                <span className="text-xs font-bold text-slate-400">{t('rp.kmMark')}</span>
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
                  {Number(station.diff_from_bank ?? 0).toFixed(2)} {t('route.m')} {t('rp.aboveBankShort')}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span>{distance_from_route_m} {t('route.m')} {t('rp.offRoute')}</span>
                  {station.agency && <span>{t('rp.agencyShort')} {station.agency}</span>}
                  {station.is_stale && <span className="text-amber-400">{t('rp.staleShort')}</span>}
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

function ObstacleList({ obstacles, onVote, votedIds, otherEvidence = false }) {
  const { t, lang } = useT()
  if (!obstacles?.length && otherEvidence) {
    // The verdict above rests on something else -- flooded road stretches or
    // gauges -- so a green "no reports on this route" beneath a red "do not
    // go" reads as the app contradicting itself. Say only what is true: no
    // one has filed a report here, and the evidence is in the lists below.
    return (
      <div className="card p-3">
        <p className="text-sm text-slate-300">{t('rp.noUserReports')}</p>
      </div>
    )
  }
  if (!obstacles?.length) {
    return (
      <div className="card border-emerald-800/50 bg-emerald-950/30 p-4">
        <p className="text-sm text-emerald-200">
          {t('rp.noReports')}
        </p>
        <p className="mt-1 text-xs text-emerald-300/70">
          {t('rp.noReportsCaveat')}
        </p>
      </div>
    )
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-slate-200">
        {t('rp.reportsStep')} ({obstacles.length})
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
                    {report.place || report.district || t('rp.unknownSpot')}
                  </p>
                  <p className="mt-0.5 text-sm font-medium" style={{ color }}>
                    {report.level_label || levelLabel(report.level)}
                    {report.depth_cm ? ` · ${t('rp.measuredShort')} ${depthText(report.depth_cm, lang)}` : ''}
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
                    <span>{t('popup.tally', { confirms: report.confirm_count, disputes: report.dispute_count })}</span>
                    {report.source === 'official' && (
                      <span className="chip bg-sky-500/15 text-sky-300">{t('rp.official')}</span>
                    )}
                  </div>
                  {safePhotoUrl(report.photo_url) && (
                    <img
                      src={safePhotoUrl(report.photo_url)}
                      alt={t('popup.photoAlt')}
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
                      {t('report.stillFlooded')}
                    </button>
                    <button
                      className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                      onClick={() => onVote(report.id, 'dispute')}
                      disabled={voted}
                    >
                      {t('report.subsided')}
                    </button>
                    {voted && <span className="self-center text-xs text-emerald-400">{t('popup.thanks')}</span>}
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
  const { t, lang } = useT()
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
    if (!origin && !originText.trim()) return setError(t('route.needOrigin'))
    if (!destination && !destinationText.trim()) return setError(t('route.needDest'))

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
      setError(err instanceof ApiError ? err.message : t('rp.checkFailed'))
    } finally {
      setBusy(false)
    }
  }

  const vote = async (reportId, choice) => {
    try {
      await api.voteReport(reportId, choice)
      setVotedIds((previous) => new Set(previous).add(reportId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('rp.voteFailed'))
    }
  }

  const route = result?.routes?.[activeRoute]
  const verdict = VERDICTS[route?.verdict || result?.verdict] || VERDICTS.clear

  return (
    <div className="space-y-4">
      {showHelp && <HowTo onClose={() => setShowHelp(false)} />}

      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-base font-bold">{t('route.title')}</h2>
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
              title={t('route.how')}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-600 text-[11px] font-bold">
                i
              </span>
              {t('route.how')}
            </button>
          </div>
        </div>
        <div className="space-y-3">
          <EndpointInput
            id="origin"
            label={t('route.from')}
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
              title={t('route.swapTitle')}
            >
              ⇅ {t('route.swap')}
            </button>
          </div>

          <EndpointInput
            id="destination"
            label={t('route.to')}
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
          {busy ? t('route.checking') : t('route.check')}
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
            {/* Weather, beside the verdict and never folded into it. Heavy
                rain is a reason to expect trouble on the way, not a claim
                that any road here is under water — the same separation the
                canal gauges get, for the same reason. The server stays quiet
                unless it is heavy enough to change a decision. */}
            {result.rain?.summary && (
              <div className="mt-3 rounded-xl border border-indigo-800 bg-indigo-950/40 px-3 py-2 text-sm text-indigo-200">
                <p className="font-semibold">🌧️ {result.rain.summary}</p>
                <p className="mt-0.5 text-xs text-indigo-300/80">
                  ฝนตกไม่ได้แปลว่าถนนท่วม แต่เป็นสัญญาณว่าอาจแย่ลงระหว่างทาง
                  {result.rain.now?.source === 'cameras' &&
                    ' · วัดจากกล้องจราจรสาธารณะที่อยู่บนเส้นทาง'}
                </p>
              </div>
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
          {/* What decided the verdict comes first: flooded road stretches
              are the strongest evidence this app has after a camera. */}
          <RoadList roads={route?.roads} attribution={result?.roads_attribution} />
          <ObstacleList
            obstacles={route?.obstacles}
            onVote={vote}
            votedIds={votedIds}
            otherEvidence={Boolean(route?.roads?.length || route?.stations?.length || (route && route.verdict !== 'clear'))}
          />
          <StationList stations={route?.stations} />

          <div className="flex flex-wrap gap-2">
            <button
              className="btn-ghost text-sm"
              onClick={() =>
                onAskChat({
                  message: `มีทางเลี่ยงจาก${result.origin_label || originText || 'ต้นทาง'}ไป${result.destination_label || destinationText || 'ปลายทาง'}ไหม`,
                  // Coordinates, not the labels: "ตำแหน่งของฉัน" and "หมุด 13.69,
                  // 100.71" are not places the assistant can look up.
                  route: {
                    origin: result.origin,
                    destination: result.destination,
                    origin_label: result.origin_label || originText || null,
                    destination_label: result.destination_label || destinationText || null,
                  },
                })
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
