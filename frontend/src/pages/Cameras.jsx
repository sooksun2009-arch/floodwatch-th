import { useEffect, useMemo, useState } from 'react'
import { api, levelLabel } from '../api'
import CameraModal from '../components/CameraModal'
import { useT } from '../i18n'


/**
 * Where to watch a road when this app has no camera on it.
 *
 * Carrying the feeds ourselves means permission from each agency, and that is
 * not done. Sending people to sites that already have them is worth more than
 * an empty list that says "no cameras match", because the question they came
 * with -- what does that road look like right now -- has an answer, just not
 * one we host.
 *
 * Labelled as somebody else's site, because a link that quietly leaves is how
 * an app spends the trust it needs for the flood reports.
 */
function ElsewhereCameras() {
  const { t } = useT()
  // Only sites checked to answer. bmatraffic.com was on this list and is
  // unreachable from outside Thailand -- the same symptom as the Bangkok gauge
  // site -- and a recommendation nobody verified is worse than a shorter list.
  const sites = [
    ['https://traffic.longdo.com/cameralist', 'cams.out.longdo', 'cams.out.longdoWhy'],
    ['https://traffic.longdo.com/', 'cams.out.longdoMap', 'cams.out.longdoMapWhy'],
  ]
  return (
    <div className="card mt-4 p-4">
      <p className="font-semibold text-slate-200">{t('cams.none.title')}</p>
      <p className="mt-1 text-sm leading-relaxed text-slate-400">{t('cams.none.body')}</p>
      <ul className="mt-4 space-y-2">
        {sites.map(([href, title, why]) => (
          <li key={href}>
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="block rounded-xl border border-slate-700 p-3 transition-colors hover:border-sky-600 hover:bg-slate-900"
            >
              <span className="flex items-center justify-between gap-3">
                <span className="font-medium text-sky-300">{t(title)}</span>
                <span className="shrink-0 text-xs text-slate-500">{t('cams.out.open')} ↗</span>
              </span>
              <span className="mt-1 block text-xs leading-relaxed text-slate-400">{t(why)}</span>
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-500">{t('cams.out.note')}</p>
    </div>
  )
}

export default function Cameras() {
  const { t } = useT()
  const [cameras, setCameras] = useState([])
  const [provinces, setProvinces] = useState([])
  const [search, setSearch] = useState('')
  const [provinceId, setProvinceId] = useState('')
  const [nearMe, setNearMe] = useState(false)
  const [active, setActive] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.provinces().then(setProvinces).catch(() => setProvinces([]))
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    const run = async (near) => {
      try {
        const data = await api.cameras({
          search: search.trim() || undefined,
          province_id: provinceId || undefined,
          near,
          limit: 500,
        })
        if (!cancelled) {
          setCameras(data)
          setError(null)
        }
      } catch {
        if (!cancelled) setError('โหลดรายการกล้องไม่สำเร็จ')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    if (nearMe && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => run(`${position.coords.latitude},${position.coords.longitude},25`),
        () => {
          setNearMe(false)
          run(undefined)
        },
        { timeout: 9000 },
      )
    } else {
      // Debounce the search box so typing does not fire a request per keystroke.
      const timer = setTimeout(() => run(undefined), 250)
      return () => {
        cancelled = true
        clearTimeout(timer)
      }
    }
    return () => {
      cancelled = true
    }
  }, [search, provinceId, nearMe])

  const grouped = useMemo(() => {
    const map = new Map()
    cameras.forEach((camera) => {
      const key = camera.province_name || 'ไม่ระบุจังหวัด'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(camera)
    })
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [cameras])

  return (
    <div className="mx-auto max-w-7xl p-3 sm:p-4">
      <h1 className="mb-1 text-xl font-bold">{t('cams.title')}</h1>
      <p className="mb-4 text-sm text-slate-400">
        {t('cams.sub')}
      </p>

      <div className="card mb-4 flex flex-wrap gap-2 p-3">
        <input
          className="field flex-1 min-w-[12rem]"
          placeholder="ค้นหาชื่อกล้อง เขต หรือหน่วยงาน"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="field w-auto"
          value={provinceId}
          onChange={(event) => setProvinceId(event.target.value)}
        >
          <option value="">ทุกจังหวัด</option>
          {provinces.map((province) => (
            <option key={province.id} value={province.id}>
              {province.name_th}
            </option>
          ))}
        </select>
        <button
          onClick={() => setNearMe((value) => !value)}
          className={nearMe ? 'btn-primary' : 'btn-ghost'}
        >
          📍 ใกล้ฉัน
        </button>
      </div>

      {error && (
        <p className="mb-3 rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {loading ? (
        <p className="py-10 text-center text-slate-400">กำลังโหลด…</p>
      ) : cameras.length === 0 ? (
        // Two different emptinesses, and they need different answers: a search
        // that matched nothing is the visitor's to fix, an app with no cameras
        // at all is ours, and only the second should send them elsewhere.
        search || provinceId || nearMe ? (
          <p className="py-10 text-center text-slate-400">{t('cams.none.filtered')}</p>
        ) : (
          <ElsewhereCameras />
        )
      ) : (
        <div className="space-y-6">
          {grouped.map(([province, list]) => (
            <section key={province}>
              <h2 className="mb-2 text-sm font-bold text-slate-300">
                {province} ({list.length})
              </h2>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {list.map((camera) => (
                  <button
                    key={camera.id}
                    onClick={() => setActive(camera)}
                    className="card p-3 text-left transition-colors hover:border-sky-700 hover:bg-slate-800/60"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium leading-snug">{camera.name}</p>
                      <span className="text-lg">📹</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {[camera.district, camera.owner_org].filter(Boolean).join(' · ') || '—'}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {camera.distance_km != null && (
                        <span className="chip bg-slate-800 text-slate-300">
                          {camera.distance_km} กม.
                        </span>
                      )}
                      {camera.is_demo && (
                        <span className="chip bg-amber-500/15 text-amber-300">ตัวอย่าง</span>
                      )}
                      {camera.health === 'offline' && (
                        <span className="chip bg-red-500/15 text-red-300">ออฟไลน์</span>
                      )}
                      {camera.nearby_flood_level && (
                        <span className="chip bg-red-500/15 text-red-300">
                          {levelLabel(camera.nearby_flood_level)}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <CameraModal camera={active} onClose={() => setActive(null)} />
    </div>
  )
}
