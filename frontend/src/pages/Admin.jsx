import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, LEVELS, levelLabel, timeAgo } from '../api'
import { useAuth } from '../auth'

const TABS = [
  ['queue', 'คิวตรวจสอบ'],
  ['live', 'ที่ขึ้นแผนที่'],
  ['cameras', 'จัดการกล้อง'],
  ['import', 'นำเข้าข้อมูลหน่วยงาน'],
  ['audit', 'บันทึกการใช้งาน'],
]

// ---------------------------------------------------------------- queue

function Queue() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    api
      .queue()
      .then((data) => {
        const rows = data.items || []
        // Unreviewed first — on a busy night these are the only rows on this
        // screen that still need a decision, and they would otherwise sink
        // under dozens already checked.
        setItems([...rows].sort((a, b) => Number(b.auto_approved) - Number(a.auto_approved)))
        setError(null)
      })
      .catch(() => setError('โหลดคิวไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const act = async (id, status, level) => {
    try {
      await api.moderate(id, { status, level })
      setItems((previous) => previous.filter((item) => item.id !== id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ดำเนินการไม่สำเร็จ')
    }
  }

  if (loading) return <p className="py-8 text-center text-slate-400">กำลังโหลด…</p>

  return (
    <div className="space-y-3">
      {error && (
        <p className="rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">รอตรวจสอบ {items.length} รายการ</p>
        <button onClick={load} className="btn-ghost text-sm">
          รีเฟรช
        </button>
      </div>

      {items.length === 0 ? (
        <p className="card p-8 text-center text-slate-400">ไม่มีรายงานค้างในคิว</p>
      ) : (
        items.map((report) => (
          <div key={report.id} className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-semibold">
                  {report.place || 'ไม่ระบุจุด'}
                  {report.auto_approved && (
                    <span className="ml-2 rounded-md border border-amber-700 bg-amber-950/50 px-1.5 py-0.5 align-middle text-xs font-normal text-amber-300">
                      ขึ้นเอง · ยังไม่มีคนตรวจ
                    </span>
                  )}
                </p>
                <p className="text-sm" style={{ color: LEVELS[report.level]?.color }}>
                  {report.level_label || levelLabel(report.level)}
                  {report.depth_cm ? ` · ${report.depth_cm} ซม.` : ''}
                </p>
                {report.description && (
                  <p className="mt-1 text-sm text-slate-400">{report.description}</p>
                )}
                <p className="mt-1 text-xs text-slate-500">
                  {[
                    report.reporter_name || 'ไม่ระบุผู้แจ้ง',
                    report.district,
                    report.province_name,
                    timeAgo(report.age_minutes),
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                <a
                  className="mt-1 inline-block text-xs text-sky-400 hover:underline"
                  href={`https://www.google.com/maps/search/?api=1&query=${report.lat},${report.lng}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  ตรวจพิกัดบนแผนที่ ({report.lat.toFixed(5)}, {report.lng.toFixed(5)})
                </a>
              </div>
              {report.photo_url && (
                <img
                  src={report.photo_url}
                  alt="ภาพประกอบรายงาน"
                  className="h-28 w-28 shrink-0 rounded-lg object-cover"
                />
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <select
                className="field w-auto py-1.5 text-sm"
                defaultValue={report.level}
                onChange={(event) => {
                  report.level = event.target.value
                }}
                aria-label="แก้ระดับน้ำก่อนอนุมัติ"
              >
                {Object.entries(LEVELS).map(([key, meta]) => (
                  <option key={key} value={key}>
                    {meta.label}
                  </option>
                ))}
              </select>
              <button
                className="btn bg-emerald-600 text-sm text-white hover:bg-emerald-500"
                onClick={() => act(report.id, 'approved', report.level)}
              >
                อนุมัติ
              </button>
              <button
                className="btn-ghost text-sm"
                onClick={() => act(report.id, 'rejected')}
              >
                ปฏิเสธ
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  )
}

// ---------------------------------------------------------------- live reports

function LiveReports() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [confirming, setConfirming] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    api
      .liveReports()
      .then((data) => {
        setItems(data.items || [])
        setError(null)
      })
      .catch(() => setError('โหลดรายงานไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const withdraw = async (report) => {
    try {
      await api.moderate(report.id, {
        status: 'rejected',
        note: 'ถอนออกจากแผนที่โดยผู้ดูแล',
      })
      setItems((previous) => previous.filter((item) => item.id !== report.id))
      setConfirming(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ถอนรายงานไม่สำเร็จ')
    }
  }

  const unreviewed = items.filter((item) => item.auto_approved).length

  if (loading) return <p className="py-8 text-center text-slate-400">กำลังโหลด…</p>

  return (
    <div className="space-y-3">
      {error && (
        <p className="rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          ขึ้นแผนที่อยู่ {items.length} รายการ
          {unreviewed > 0 && (
            <span className="text-amber-300"> · ยังไม่มีคนตรวจ {unreviewed}</span>
          )}
        </p>
        <button onClick={load} className="btn-ghost text-sm">
          รีเฟรช
        </button>
      </div>

      {items.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="text-slate-400">ยังไม่มีรายงานบนแผนที่</p>
          <p className="mt-1 text-xs text-slate-500">
            รายงานที่ขึ้นแผนที่แล้วจะมาแสดงที่นี่ ทั้งที่คุณอนุมัติเองและที่ระบบให้ขึ้นอัตโนมัติ
            (แนบรูป หรือมีคนแจ้งจุดเดียวกันตั้งแต่ 2 ราย) ถอนออกได้ถ้าพบว่าไม่ถูกต้อง
          </p>
        </div>
      ) : (
        items.map((report) => (
          <div key={report.id} className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{report.place || 'ไม่ระบุจุด'}</p>
                <p className="text-sm" style={{ color: LEVELS[report.level]?.color }}>
                  {report.level_label || levelLabel(report.level)}
                  {report.depth_cm ? ` · ${report.depth_cm} ซม.` : ''}
                </p>
                {report.description && (
                  <p className="mt-1 text-sm text-slate-400">{report.description}</p>
                )}
                <p className="mt-1 text-xs text-slate-500">
                  {[
                    report.reporter_name || 'ไม่ระบุผู้แจ้ง',
                    report.province_name,
                    timeAgo(report.age_minutes),
                    `ยืนยัน ${report.confirm_count} · แย้ง ${report.dispute_count}`,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                <a
                  className="mt-1 inline-block text-xs text-sky-400 hover:underline"
                  href={`https://www.google.com/maps/search/?api=1&query=${report.lat},${report.lng}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  ดูพิกัดบนแผนที่
                </a>
              </div>
              {report.photo_url && (
                <img
                  src={report.photo_url}
                  alt="ภาพประกอบรายงาน"
                  className="h-24 w-24 shrink-0 rounded-lg object-cover"
                />
              )}
            </div>

            <div className="mt-3">
              {confirming === report.id ? (
                // Taking a pin off a live flood map is worth one deliberate
                // second — a mis-tap here hides a real hazard from drivers.
                <div className="flex flex-wrap items-center gap-2 rounded-xl border border-red-900 bg-red-950/40 p-3">
                  <span className="text-sm text-red-200">
                    ถอนรายงานนี้ออกจากแผนที่?
                  </span>
                  <button
                    className="btn bg-red-700 text-sm text-white hover:bg-red-600"
                    onClick={() => withdraw(report)}
                  >
                    ยืนยันถอน
                  </button>
                  <button className="btn-ghost text-sm" onClick={() => setConfirming(null)}>
                    ยกเลิก
                  </button>
                </div>
              ) : (
                <button
                  className="btn-ghost text-sm"
                  onClick={() => setConfirming(report.id)}
                >
                  ถอนออกจากแผนที่
                </button>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  )
}

// ---------------------------------------------------------------- cameras

const EMPTY_CAMERA = {
  name: '',
  lat: '',
  lng: '',
  stream_type: 'snapshot',
  stream_url: '',
  refresh_sec: 15,
  owner_org: '',
  district: '',
  source_page: '',
  is_demo: false,
}

function CameraAdmin() {
  const [cameras, setCameras] = useState([])
  const [form, setForm] = useState(EMPTY_CAMERA)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    api
      .cameras({ include_inactive: true, limit: 500 })
      .then(setCameras)
      .catch(() => setError('โหลดรายการกล้องไม่สำเร็จ'))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const set = (key) => (event) =>
    setForm({
      ...form,
      [key]: event.target.type === 'checkbox' ? event.target.checked : event.target.value,
    })

  // Accept a pasted Google Maps link in the latitude box and split it.
  const onLatPaste = (event) => {
    const text = event.clipboardData.getData('text')
    const match = text.match(/(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{2,3}\.\d{3,})/)
    if (match) {
      event.preventDefault()
      setForm({ ...form, lat: match[1], lng: match[2] })
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await api.createCamera({
        ...form,
        lat: Number(form.lat),
        lng: Number(form.lng),
        refresh_sec: Number(form.refresh_sec) || 15,
        owner_org: form.owner_org || null,
        district: form.district || null,
        source_page: form.source_page || null,
      })
      setForm(EMPTY_CAMERA)
      setMessage('เพิ่มกล้องแล้ว')
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เพิ่มกล้องไม่สำเร็จ')
    } finally {
      setBusy(false)
    }
  }

  const runHealthCheck = async () => {
    setBusy(true)
    setMessage(null)
    try {
      const results = await api.cameraHealthCheck()
      const offline = results.filter((camera) => camera.health === 'offline').length
      setMessage(`ตรวจแล้ว ${results.length} ตัว · ใช้งานไม่ได้ ${offline} ตัว`)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ตรวจสถานะไม่สำเร็จ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="card space-y-3 p-4">
        <h2 className="font-bold">เพิ่มกล้องใหม่</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="label">ชื่อกล้อง</label>
            <input className="field" value={form.name} onChange={set('name')} required />
          </div>
          <div>
            <label className="label">ละติจูด (วาง "lat, lng" ได้เลย)</label>
            <input
              className="field"
              value={form.lat}
              onChange={set('lat')}
              onPaste={onLatPaste}
              required
            />
          </div>
          <div>
            <label className="label">ลองจิจูด</label>
            <input className="field" value={form.lng} onChange={set('lng')} required />
          </div>
          <div>
            <label className="label">ประเภทสตรีม</label>
            <select className="field" value={form.stream_type} onChange={set('stream_type')}>
              <option value="snapshot">ภาพนิ่ง refresh เป็นรอบ (กล้องราชการส่วนใหญ่)</option>
              <option value="hls">HLS (.m3u8)</option>
              <option value="mjpeg">MJPEG</option>
              <option value="youtube">YouTube Live</option>
              <option value="iframe">ฝังหน้าเว็บ (iframe)</option>
            </select>
          </div>
          <div>
            <label className="label">รอบรีเฟรช (วินาที)</label>
            <input
              type="number"
              min="3"
              max="600"
              className="field"
              value={form.refresh_sec}
              onChange={set('refresh_sec')}
            />
          </div>
          <div className="sm:col-span-2">
            <label className="label">URL สตรีม / ภาพ</label>
            <input
              className="field"
              value={form.stream_url}
              onChange={set('stream_url')}
              placeholder="https://..."
              required
            />
          </div>
          <div>
            <label className="label">หน่วยงานเจ้าของ</label>
            <input
              className="field"
              value={form.owner_org}
              onChange={set('owner_org')}
              placeholder="เช่น กทม., กรมทางหลวง"
            />
          </div>
          <div>
            <label className="label">เขต/อำเภอ</label>
            <input className="field" value={form.district} onChange={set('district')} />
          </div>
          <div className="sm:col-span-2">
            <label className="label">หน้าเว็บต้นทาง (ใช้เป็น Referer ตอนดึงภาพ)</label>
            <input
              className="field"
              value={form.source_page}
              onChange={set('source_page')}
              placeholder="https://..."
            />
            <p className="mt-1 text-xs text-slate-500">
              กล้องหลายแห่งส่งภาพเฉพาะเมื่อ Referer ตรงกับหน้าดูของหน่วยงาน — ใส่ไว้ช่วยให้ดึงภาพผ่าน
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300 sm:col-span-2">
            <input type="checkbox" checked={form.is_demo} onChange={set('is_demo')} />
            เป็นสตรีมตัวอย่าง (จะติดป้ายเตือนผู้ใช้ว่าไม่ใช่ภาพจริง)
          </label>
        </div>

        {error && (
          <p className="rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}
        {message && <p className="text-sm text-emerald-400">{message}</p>}

        <div className="flex gap-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            เพิ่มกล้อง
          </button>
          <button type="button" onClick={runHealthCheck} className="btn-ghost" disabled={busy}>
            ตรวจสถานะกล้องทั้งหมด
          </button>
        </div>
      </form>

      <div className="card overflow-hidden">
        <h2 className="border-b border-slate-800 p-4 font-bold">
          กล้องในระบบ ({cameras.length})
        </h2>
        <div className="max-h-[28rem] overflow-y-auto">
          {cameras.map((camera) => (
            <div
              key={camera.id}
              className="flex items-center gap-3 border-b border-slate-800/60 p-3 text-sm"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{camera.name}</p>
                <p className="truncate text-xs text-slate-500">
                  {camera.stream_type} · {camera.owner_org || 'ไม่ระบุหน่วยงาน'} ·{' '}
                  {camera.province_name || '—'}
                </p>
              </div>
              <span
                className={`chip ${
                  camera.health === 'online'
                    ? 'bg-emerald-500/15 text-emerald-300'
                    : camera.health === 'offline'
                      ? 'bg-red-500/15 text-red-300'
                      : 'bg-slate-800 text-slate-400'
                }`}
              >
                {camera.health === 'online'
                  ? 'ใช้ได้'
                  : camera.health === 'offline'
                    ? 'ออฟไลน์'
                    : 'ยังไม่ตรวจ'}
              </span>
              <button
                className="text-xs text-slate-400 hover:text-slate-200"
                onClick={async () => {
                  await api.updateCamera(camera.id, { is_active: !camera.is_active })
                  load()
                }}
              >
                {camera.is_active ? 'ปิดใช้' : 'เปิดใช้'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- import

function ImportPanel() {
  const [text, setText] = useState('')
  const [sourceName, setSourceName] = useState('กทม. รายงานเขต')
  const [autoApprove, setAutoApprove] = useState(true)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const run = async (dryRun, file) => {
    setBusy(true)
    setError(null)
    try {
      const data = file
        ? await api.importFile(file, { sourceName, autoApprove, dryRun })
        : await api.importPaste({
            text,
            source_name: sourceName,
            auto_approve: autoApprove,
            dry_run: dryRun,
          })
      setResult(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'นำเข้าข้อมูลไม่สำเร็จ')
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="card p-4 text-sm leading-relaxed text-slate-300">
        <h2 className="mb-2 font-bold text-slate-100">นำเข้ารายงานจากหน่วยงาน</h2>
        <p>
          วางรายการที่หน่วยงานประกาศ (เช่น รายงานจุดน้ำท่วมของสำนักงานเขต) หรืออัปโหลดไฟล์
          .csv / .xlsx ได้โดยตรง ระบบจะอ่านชื่อถนน เขต ระดับน้ำ และ<strong>พิกัดจากลิงก์ Google Maps</strong>{' '}
          ให้อัตโนมัติ
        </p>
        <p className="mt-2 text-slate-400">
          แต่ละรายการต้องมีพิกัดหรือลิงก์แผนที่ รายการที่ไม่มีพิกัดจะถูกข้ามพร้อมแจ้งเหตุผล
          นำเข้าซ้ำรายการเดิมจะเป็นการอัปเดต ไม่สร้างซ้ำ
        </p>
      </div>

      <div className="card space-y-3 p-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">ชื่อแหล่งข้อมูล</label>
            <input
              className="field"
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
            />
          </div>
          <label className="flex items-end gap-2 pb-2.5 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={autoApprove}
              onChange={(event) => setAutoApprove(event.target.checked)}
            />
            ขึ้นแผนที่ทันที (ไม่ต้องรอตรวจ)
          </label>
        </div>

        <div>
          <label className="label">วางข้อความรายการ</label>
          <textarea
            className="field font-mono text-sm"
            rows={10}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={`21. ถ.วชิรธรรมสาธิต
ช่วงน้ำท่วม: บริเวณใกล้ ซ.วัดทุ่ง
ช่วง 3 แยกซอยวัดทุ่ง ท่วมสูง 20 ซม. หรือมากกว่า
เขตพระโขนง
https://maps.google.com/?q=13.686460,100.635200

(เว้นบรรทัดว่างคั่นระหว่างรายการ)`}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            className="btn-ghost"
            disabled={busy || !text.trim()}
            onClick={() => run(true)}
          >
            ทดลองอ่าน (ยังไม่บันทึก)
          </button>
          <button
            className="btn-primary"
            disabled={busy || !text.trim()}
            onClick={() => run(false)}
          >
            นำเข้าจริง
          </button>
          <label className="btn-ghost cursor-pointer">
            อัปโหลด .csv / .xlsx
            <input
              type="file"
              accept=".csv,.xlsx,.xlsm,.tsv"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) run(true, file)
                event.target.value = ''
              }}
            />
          </label>
        </div>

        {error && (
          <p className="rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}
      </div>

      {result && (
        <div className="card p-4">
          <h3 className="mb-2 font-bold">
            {result.dry_run ? 'ผลการทดลองอ่าน' : 'นำเข้าเรียบร้อย'}
          </h3>
          <p className="text-sm text-slate-300">
            อ่านได้ {result.parsed} รายการ · เพิ่มใหม่ {result.created} · อัปเดต {result.updated} ·
            ข้าม {result.skipped}
          </p>

          {result.errors?.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-amber-300">
              {result.errors.map((message) => (
                <li key={message}>• {message}</li>
              ))}
            </ul>
          )}

          {result.preview?.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="p-2 font-medium">จุด</th>
                    <th className="p-2 font-medium">เขต</th>
                    <th className="p-2 font-medium">ระดับ</th>
                    <th className="p-2 font-medium">ลึก</th>
                    <th className="p-2 font-medium">พิกัด</th>
                  </tr>
                </thead>
                <tbody>
                  {result.preview.map((row, index) => (
                    <tr key={index} className="border-t border-slate-800">
                      <td className="p-2">{row.place}</td>
                      <td className="p-2 text-slate-400">{row.district || '—'}</td>
                      <td className="p-2" style={{ color: LEVELS[row.level]?.color }}>
                        {LEVELS[row.level]?.short || row.level}
                      </td>
                      <td className="p-2 text-slate-400">
                        {row.depth_cm != null ? `${row.depth_cm} ซม.` : '—'}
                      </td>
                      <td className="p-2 text-xs text-slate-500">
                        {row.lat.toFixed(5)}, {row.lng.toFixed(5)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- audit

function Audit() {
  const [rows, setRows] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    api
      .audit()
      .then(setRows)
      .catch(() => setError('บัญชีนี้ต้องเป็นผู้ดูแลระบบจึงจะดูบันทึกได้'))
  }, [])

  if (error) return <p className="card p-6 text-center text-slate-400">{error}</p>

  return (
    <div className="card overflow-hidden">
      <div className="max-h-[32rem] overflow-y-auto">
        {rows.map((row) => (
          <div key={row.id} className="border-b border-slate-800/60 p-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <span className="font-medium">{row.action}</span>
              <span className="text-xs text-slate-500">
                {new Date(row.created_at).toLocaleString('th-TH')}
              </span>
            </div>
            <p className="text-xs text-slate-400">
              {row.actor_name} · {row.entity}
              {row.detail ? ` · ${row.detail}` : ''}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- shell

export default function Admin() {
  const { user } = useAuth()
  const [tab, setTab] = useState('queue')

  return (
    <div className="mx-auto max-w-5xl p-3 sm:p-4">
      <h1 className="mb-1 text-xl font-bold">หน้าผู้ดูแลระบบ</h1>
      <p className="mb-4 text-sm text-slate-400">
        {user?.display_name || user?.username} · สิทธิ์ {user?.role}
      </p>

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-800">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`whitespace-nowrap px-3 py-2 text-sm font-medium transition-colors ${
              tab === key
                ? 'border-b-2 border-sky-500 text-white'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'queue' && <Queue />}
      {tab === 'live' && <LiveReports />}
      {tab === 'cameras' && <CameraAdmin />}
      {tab === 'import' && <ImportPanel />}
      {tab === 'audit' && <Audit />}
    </div>
  )
}
