import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useT } from '../i18n'

/**
 * "Your area": what is happening in the reader's own province, before they
 * type anything.
 *
 * The server sends every province at once, centroids included, and the
 * nearest one is picked here in the browser. A position from "use my
 * location" is used for that one comparison and dropped; it is never sent
 * anywhere. The chosen province is remembered on this device only.
 *
 * "Normal" is worded as "nothing reported in the data we have", never "safe":
 * a reader already told us about a route shown as clear that was not, and
 * this card must not make the same promise on a larger scale.
 */
const PROVINCE_KEY = 'floodwatch.province'
const REFRESH_MS = 3 * 60 * 1000

const STYLE = {
  danger: 'border-red-700/70 bg-red-950/40 text-red-100',
  watch: 'border-amber-700/70 bg-amber-950/30 text-amber-100',
  normal: 'border-emerald-800/70 bg-emerald-950/30 text-emerald-100',
}
const DOT = { danger: 'bg-red-500', watch: 'bg-amber-400', normal: 'bg-emerald-400' }

function load() {
  try {
    return localStorage.getItem(PROVINCE_KEY)
  } catch {
    return null
  }
}

function save(name) {
  try {
    localStorage.setItem(PROVINCE_KEY, name)
  } catch {
    /* remembered for this visit only */
  }
}

function distanceKm(aLat, aLng, bLat, bLng) {
  const rad = Math.PI / 180
  const dLat = (bLat - aLat) * rad
  const dLng = (bLng - aLng) * rad
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLng / 2) ** 2
  return 12742 * Math.asin(Math.sqrt(h))
}

export default function AreaCard({ onFocus }) {
  const { t, lang } = useT()
  const [data, setData] = useState(null)
  const [chosen, setChosen] = useState(load)
  const [open, setOpen] = useState(false)
  const [locating, setLocating] = useState(false)
  const [note, setNote] = useState(null)

  useEffect(() => {
    let alive = true
    const read = () => api.provincesOverview()
      .then((d) => alive && setData(d))
      .catch(() => {})
    read()
    const timer = setInterval(read, REFRESH_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  const provinces = data?.provinces || []
  const mine = provinces.find((p) => p.name_th === chosen) || null
  const worrying = useMemo(
    () => provinces.filter((p) => p.status !== 'normal' && p.name_th !== chosen).slice(0, 5),
    [provinces, chosen],
  )
  const sorted = useMemo(
    () => [...provinces].sort((a, b) => a.name_th.localeCompare(b.name_th, 'th')),
    [provinces],
  )
  const label = (p) => (lang === 'en' && p.name_en ? p.name_en : p.name_th)

  const pick = useCallback((name) => {
    setChosen(name)
    save(name)
    setNote(null)
  }, [])

  const focus = (p) => onFocus?.({ lat: p.lat, lng: p.lng, zoom: 9, key: Date.now() })

  const locate = () => {
    if (!navigator.geolocation) {
      setNote(t('area.noGeo'))
      return
    }
    setLocating(true)
    setNote(null)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false)
        if (!provinces.length) return
        // Compared here and forgotten: the position never leaves this page.
        const nearest = provinces.reduce((best, p) =>
          distanceKm(coords.latitude, coords.longitude, p.lat, p.lng)
            < distanceKm(coords.latitude, coords.longitude, best.lat, best.lng) ? p : best)
        pick(nearest.name_th)
        focus(nearest)
      },
      () => {
        setLocating(false)
        setNote(t('area.geoDenied'))
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 10 * 60 * 1000 },
    )
  }

  if (!data) return null

  const facts = (p) => {
    const parts = []
    if (p.reports) parts.push(t('area.reports', { n: p.reports }))
    if (p.impassable) parts.push(t('area.impassable', { n: p.impassable }))
    if (p.overflowing) parts.push(t('area.overflowing', { n: p.overflowing }))
    if (p.raining) parts.push(t('area.raining', { n: p.raining }))
    return parts
  }

  const select = (
    <select
      value={mine ? mine.name_th : ''}
      onChange={(e) => e.target.value && pick(e.target.value)}
      aria-label={t('area.choose')}
      className="max-w-[11rem] rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 lg:py-0.5"
    >
      <option value="">{t('area.choose')}</option>
      {sorted.map((p) => (
        <option key={p.name_th} value={p.name_th}>{label(p)}</option>
      ))}
    </select>
  )

  const locateButton = (
    <button
      onClick={locate}
      disabled={locating}
      className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50 lg:py-0.5"
    >
      📍 {locating ? t('area.locating') : t('area.useLocation')}
    </button>
  )

  if (!mine) {
    return (
      <div className="mb-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-300 lg:flex lg:h-9 lg:items-center lg:py-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-100">{t('area.title')}</span>
          {locateButton}
          {select}
        </div>
        {worrying.length > 0 && (
          <p className="mt-1.5 text-slate-400 lg:hidden">
            {t('area.worryingNow')}{' '}
            {worrying.map((p, i) => (
              <button key={p.name_th} onClick={() => focus(p)}
                className="mr-1 underline decoration-slate-600 underline-offset-2 hover:text-slate-200">
                {label(p)}{i < worrying.length - 1 ? ',' : ''}
              </button>
            ))}
          </p>
        )}
        {note && <p className="mt-1 text-amber-300 lg:ml-2 lg:mt-0 lg:truncate">{note}</p>}
      </div>
    )
  }

  const summary = facts(mine)
  return (
    // relative: on wide screens the details open as a dropdown over the map
    // instead of pushing it down -- the map there is sized to end exactly at
    // the bottom of the window, and a taller card would push its buttons
    // onto the chat button and its credit off the screen.
    <div className={`relative mb-2 rounded-xl border px-3 py-2 text-xs lg:flex lg:h-9 lg:items-center lg:py-0 ${STYLE[mine.status]}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left"
      >
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[mine.status]}`} />
        <span className="shrink-0 font-semibold">📍 {label(mine)}</span>
        <span className="shrink-0 font-semibold">· {t(`area.status.${mine.status}`)}</span>
        <span className="min-w-0 flex-1 truncate opacity-80">
          {summary.length ? `· ${summary.join(' · ')}` : ''}
        </span>
        <span className="shrink-0 opacity-70">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 border-t border-white/10 pt-2 lg:absolute lg:inset-x-0 lg:top-full lg:z-40 lg:mt-1 lg:rounded-xl lg:border lg:border-slate-700 lg:bg-slate-900 lg:p-3 lg:shadow-2xl">
          <p className="leading-relaxed opacity-90">
            {summary.length ? summary.join(' · ') : t('area.nothing')}
            {mine.stations > 0 && ` · ${t('area.stations', { n: mine.stations })}`}
            {mine.cameras > 0 && ` · ${t('area.cameras', { n: mine.cameras })}`}
          </p>
          {mine.status === 'normal' && (
            <p className="opacity-70">{t('area.normalCaveat')}</p>
          )}
          {data.rain_known === false && <p className="opacity-60">{t('area.noRain')}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => focus(mine)}
              className="rounded-lg bg-white/10 px-2 py-1 font-semibold hover:bg-white/20">
              {t('area.showOnMap')}
            </button>
            {locateButton}
            {select}
          </div>
          {worrying.length > 0 && (
            <div>
              <p className="mb-1 opacity-70">{t('area.worryingNow')}</p>
              <div className="flex flex-wrap gap-1.5">
                {worrying.map((p) => (
                  <button key={p.name_th} onClick={() => focus(p)}
                    className="flex items-center gap-1 rounded-full border border-white/15 px-2 py-0.5 hover:bg-white/10">
                    <span className={`h-2 w-2 rounded-full ${DOT[p.status]}`} />
                    {label(p)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {note && <p className="text-amber-300">{note}</p>}
          <p className="opacity-50">{t('area.privacy')}</p>
        </div>
      )}
    </div>
  )
}
