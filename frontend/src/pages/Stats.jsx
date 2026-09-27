import { useEffect, useState } from 'react'
import { api, LEVELS, levelLabel } from '../api'

function StatTile({ label, value, hint, tone = 'text-slate-100' }) {
  return (
    <div className="card p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${tone}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

// Minimal inline bar chart — a charting library is not worth the bundle for one
// 48-bar sparkline.
function Timeline({ points }) {
  if (!points?.length) return null
  const max = Math.max(1, ...points.map((point) => point.total))
  return (
    <div className="card p-4">
      <h2 className="mb-3 text-sm font-bold text-slate-300">รายงานใหม่ต่อชั่วโมง (48 ชม.)</h2>
      <div className="flex h-28 items-end gap-[2px]">
        {points.map((point) => (
          <div
            key={point.bucket}
            className="flex-1 rounded-t bg-sky-600/70 transition-colors hover:bg-sky-400"
            style={{ height: `${Math.max(2, (point.total / max) * 100)}%` }}
            title={`${point.bucket.replace('T', ' ')} — ${point.total} รายงาน`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-slate-500">
        <span>48 ชม.ก่อน</span>
        <span>สูงสุด {max} รายงาน/ชม.</span>
        <span>ตอนนี้</span>
      </div>
    </div>
  )
}

export default function Stats() {
  const [summary, setSummary] = useState(null)
  const [provinces, setProvinces] = useState([])
  const [timeline, setTimeline] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    const load = () =>
      Promise.all([api.summary(), api.byProvince(), api.timeline(48)])
        .then(([summaryData, provinceData, timelineData]) => {
          setSummary(summaryData)
          setProvinces(provinceData)
          setTimeline(timelineData)
          setError(null)
        })
        .catch(() => setError('โหลดสถิติไม่สำเร็จ'))

    load()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 120_000)
    return () => clearInterval(timer)
  }, [])

  if (error) return <p className="p-8 text-center text-red-300">{error}</p>
  if (!summary) return <p className="p-8 text-center text-slate-400">กำลังโหลด…</p>

  const worstCount =
    (summary.by_level.severe || 0) + (summary.by_level.closed || 0)

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-3 sm:p-4">
      <h1 className="text-xl font-bold">ภาพรวมสถานการณ์</h1>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="จุดน้ำท่วมที่ยืนยันแล้ว"
          value={summary.active_reports}
          hint={`แจ้งเข้ามาใน 24 ชม. ${summary.reports_last_24h} รายการ`}
        />
        <StatTile
          label="จุดที่ผ่านไม่ได้"
          value={worstCount}
          tone={worstCount > 0 ? 'text-red-400' : 'text-slate-100'}
          hint="ระดับรุนแรงหรือปิดการจราจร"
        />
        <StatTile
          label="จังหวัดที่ได้รับผลกระทบ"
          value={summary.provinces_affected}
        />
        <StatTile
          label="กล้อง CCTV ที่ใช้ได้"
          value={`${summary.cameras_active}/${summary.cameras_total}`}
        />
      </div>

      <div className="card p-4">
        <h2 className="mb-3 text-sm font-bold text-slate-300">แยกตามระดับน้ำ</h2>
        {summary.active_reports === 0 ? (
          <p className="text-sm text-slate-400">ตอนนี้ไม่มีจุดน้ำท่วมที่ยืนยันแล้วในระบบ</p>
        ) : (
          <div className="space-y-2">
            {Object.entries(LEVELS).map(([key, meta]) => {
              const count = summary.by_level[key] || 0
              const percent = (count / summary.active_reports) * 100
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 text-xs text-slate-400">{meta.short}</span>
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${percent}%`, background: meta.color }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-sm font-medium">{count}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Timeline points={timeline} />

      <div className="card overflow-hidden">
        <h2 className="border-b border-slate-800 p-4 text-sm font-bold text-slate-300">
          จังหวัดที่มีรายงานมากที่สุด
        </h2>
        {provinces.length === 0 ? (
          <p className="p-4 text-sm text-slate-400">ยังไม่มีข้อมูล</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/60 text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="p-3 font-medium">จังหวัด</th>
                  <th className="p-3 font-medium">จุดทั้งหมด</th>
                  <th className="p-3 font-medium">ระดับหนักสุด</th>
                  <th className="p-3 font-medium">ผ่านไม่ได้</th>
                </tr>
              </thead>
              <tbody>
                {provinces.map((row) => (
                  <tr key={`${row.province_id}-${row.province_name}`} className="border-t border-slate-800">
                    <td className="p-3 font-medium">{row.province_name}</td>
                    <td className="p-3">{row.total}</td>
                    <td className="p-3" style={{ color: LEVELS[row.worst_level]?.color }}>
                      {levelLabel(row.worst_level)}
                    </td>
                    <td className="p-3">
                      {row.impassable > 0 ? (
                        <span className="text-red-400">{row.impassable}</span>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="px-1 text-xs text-slate-500">
        อัปเดตล่าสุด {new Date(summary.updated_at).toLocaleString('th-TH')}
      </p>
    </div>
  )
}
