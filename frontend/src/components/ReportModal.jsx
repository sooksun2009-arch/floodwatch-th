import { useEffect, useState } from 'react'
import { api, ApiError, LEVELS, parseCoords } from '../api'

// Ordered worst-last so the picker reads like a rising scale.
const LEVEL_ORDER = ['puddle', 'shallow', 'deep', 'severe', 'closed']

const LEVEL_HINT = {
  puddle: 'น้ำแค่แฉะผิวถนน ต่ำกว่าขอบฟุตบาท',
  shallow: 'ประมาณครึ่งล้อรถเก๋ง ท่วมข้อเท้าถึงหน้าแข้ง',
  deep: 'ถึงกันชนหน้า ท่วมเข่า รถเก๋งเริ่มเสี่ยง',
  severe: 'เลยฝากระโปรง ท่วมเอว รถเก๋งผ่านไม่ได้',
  closed: 'เจ้าหน้าที่ปิดเส้นทาง หรือมีแผงกั้น',
}

export default function ReportModal({ open, onClose, initialPoint, onPickOnMap, onSubmitted }) {
  const [point, setPoint] = useState(initialPoint || null)
  const [coordText, setCoordText] = useState('')
  const [coordNote, setCoordNote] = useState(null)
  const [level, setLevel] = useState('shallow')
  const [depth, setDepth] = useState('')
  const [place, setPlace] = useState('')
  const [description, setDescription] = useState('')
  const [reporterName, setReporterName] = useState('')
  const [passable, setPassable] = useState(null)
  const [photo, setPhoto] = useState(null)
  const [photoPreview, setPhotoPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  useEffect(() => {
    if (open) {
      setPoint(initialPoint || null)
      setCoordText('')
      setCoordNote(null)
      setError(null)
      setDone(null)
    }
  }, [open, initialPoint])

  // Revoke the object URL when the preview changes or the modal unmounts,
  // otherwise each chosen photo leaks a blob for the page's lifetime.
  useEffect(() => () => photoPreview && URL.revokeObjectURL(photoPreview), [photoPreview])

  const locate = () => {
    if (!navigator.geolocation) return setError('เบราว์เซอร์นี้ไม่รองรับการระบุตำแหน่ง')
    setBusy(true)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setBusy(false)
        setPoint({ lat: position.coords.latitude, lng: position.coords.longitude })
        setError(null)
      },
      () => {
        setBusy(false)
        setError('ระบุตำแหน่งไม่สำเร็จ — กดปุ่ม “เลือกจุดบนแผนที่” ด้านล่างแทนได้')
      },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  // Accept whatever the reporter pasted: a coordinate pair, the degrees form,
  // or a Google Maps link. GPS alone is not enough — it fails indoors, on a
  // desktop, and whenever someone reports a spot they are not standing at.
  const readCoordText = (raw) => {
    setCoordText(raw)
    if (!raw.trim()) return setCoordNote(null)

    const parsed = parseCoords(raw)
    if (parsed) {
      setPoint(parsed)
      setCoordNote({ ok: true, text: `อ่านพิกัดได้: ${parsed.lat.toFixed(5)}, ${parsed.lng.toFixed(5)}` })
      setError(null)
    } else {
      setCoordNote({ ok: false, text: 'ยังอ่านพิกัดไม่ได้ — ต้องเป็นพิกัดในประเทศไทย หรือลิงก์ที่มีพิกัดอยู่ข้างใน' })
    }
  }

  const pickPhoto = (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (file.size > 8 * 1024 * 1024) return setError('รูปใหญ่เกิน 8 MB')
    setPhoto(file)
    if (photoPreview) URL.revokeObjectURL(photoPreview)
    setPhotoPreview(URL.createObjectURL(file))
    setError(null)
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!point) return setError('ต้องระบุตำแหน่งก่อน กดปุ่มใช้ตำแหน่งของฉัน วางพิกัด หรือปักหมุดบนแผนที่')
    // Checked here as well as on the server: a form that accepts everything
    // and then rejects it wastes the photo upload and the person's time.
    if (!photo) return setError('ต้องแนบรูปถ่ายจุดที่น้ำท่วมด้วย')

    setBusy(true)
    setError(null)
    try {
      let photoUrl = null
      if (photo) {
        // Upload first: if this fails the report has not been filed yet, so the
        // user can retry without creating a duplicate.
        const uploaded = await api.upload(photo)
        photoUrl = uploaded.url
      }
      const created = await api.createReport({
        lat: point.lat,
        lng: point.lng,
        level,
        depth_cm: depth === '' ? null : Number(depth),
        passable,
        place: place.trim() || null,
        description: description.trim() || null,
        reporter_name: reporterName.trim() || null,
        photo_url: photoUrl,
      })
      setDone(created)
      onSubmitted?.(created)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ส่งรายงานไม่สำเร็จ ลองใหม่อีกครั้ง')
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 sm:items-center sm:p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="card max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-b-none sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="แจ้งน้ำท่วม"
      >
        {done ? (
          <div className="p-6 text-center">
            <div className="mb-3 text-4xl">🙏</div>
            <h3 className="text-lg font-bold">ขอบคุณที่ช่วยแจ้งครับ</h3>
            <p className="mt-2 text-sm text-slate-400">
              {done.status === 'approved'
                ? 'รายงานขึ้นแผนที่แล้ว คนที่กำลังจะผ่านเส้นทางนี้เห็นได้ทันที'
                : 'รายงานเข้าคิวตรวจสอบแล้ว — ถ้ามีคนแจ้งจุดเดียวกันอีกราย จะขึ้นแผนที่เองทันที'}
            </p>
            <button className="btn-primary mt-5 w-full" onClick={onClose}>
              ปิด
            </button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <div className="flex items-center justify-between border-b border-slate-800 p-4">
              <h3 className="text-base font-bold">แจ้งน้ำท่วม</h3>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg px-2 py-1 text-2xl leading-none text-slate-400 hover:bg-slate-800"
                aria-label="ปิด"
              >
                ×
              </button>
            </div>

            <div className="space-y-4 p-4">
              <div>
                <span className="label">ตำแหน่ง</span>
                {point ? (
                  <p className="rounded-xl border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-200">
                    ปักหมุดแล้ว: {point.lat.toFixed(5)}, {point.lng.toFixed(5)}
                  </p>
                ) : (
                  <p className="rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-400">
                    ยังไม่ได้ระบุตำแหน่ง
                  </p>
                )}
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <button type="button" onClick={locate} className="btn-ghost text-sm">
                    📍 ใช้ตำแหน่งปัจจุบันของฉัน
                  </button>
                  {onPickOnMap && (
                    <button type="button" onClick={onPickOnMap} className="btn-ghost text-sm">
                      🗺️ เลือกจุดบนแผนที่
                    </button>
                  )}
                </div>

                <label className="label mt-3" htmlFor="coords">
                  หรือวางพิกัด / ลิงก์ Google Maps
                </label>
                <input
                  id="coords"
                  className="field"
                  value={coordText}
                  onChange={(event) => readCoordText(event.target.value)}
                  placeholder="13.68646, 100.63520 หรือวางลิงก์แผนที่"
                  inputMode="text"
                  autoComplete="off"
                  spellCheck="false"
                />
                {coordNote && (
                  <p className={`mt-1 text-xs ${coordNote.ok ? 'text-emerald-300' : 'text-amber-300'}`}>
                    {coordNote.text}
                  </p>
                )}
                <p className="mt-1 text-xs text-slate-500">
                  ใน Google Maps กดค้างที่จุดนั้น แล้วแตะพิกัดที่ขึ้นมาเพื่อคัดลอก
                  หรือกดแชร์แล้วคัดลอกลิงก์มาวางก็ได้
                </p>
              </div>

              <div>
                <span className="label">ระดับน้ำ</span>
                <div className="space-y-1.5">
                  {LEVEL_ORDER.map((key) => (
                    <label
                      key={key}
                      className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                        level === key
                          ? 'border-sky-500 bg-sky-500/10'
                          : 'border-slate-700 hover:bg-slate-800/50'
                      }`}
                    >
                      <input
                        type="radio"
                        name="level"
                        className="mt-1"
                        checked={level === key}
                        onChange={() => setLevel(key)}
                      />
                      <span className="min-w-0">
                        <span
                          className="block text-sm font-semibold"
                          style={{ color: LEVELS[key].color }}
                        >
                          {LEVELS[key].label}
                        </span>
                        <span className="block text-xs text-slate-400">{LEVEL_HINT[key]}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label" htmlFor="depth">
                    ความลึก (ซม.) ถ้าประมาณได้
                  </label>
                  <input
                    id="depth"
                    type="number"
                    min="0"
                    max="1000"
                    className="field"
                    value={depth}
                    onChange={(event) => setDepth(event.target.value)}
                    placeholder="เช่น 25"
                  />
                </div>
                <div>
                  <span className="label">รถเก๋งผ่านได้ไหม</span>
                  <div className="flex gap-2">
                    {[
                      ['ได้', true],
                      ['ไม่ได้', false],
                    ].map(([text, value]) => (
                      <button
                        key={text}
                        type="button"
                        onClick={() => setPassable(passable === value ? null : value)}
                        className={`flex-1 rounded-xl border py-2.5 text-sm transition-colors ${
                          passable === value
                            ? 'border-sky-500 bg-sky-500/10 text-sky-200'
                            : 'border-slate-700 text-slate-300 hover:bg-slate-800'
                        }`}
                      >
                        {text}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <label className="label" htmlFor="place">
                  จุดสังเกต / ถนน / แยก
                </label>
                <input
                  id="place"
                  className="field"
                  value={place}
                  onChange={(event) => setPlace(event.target.value)}
                  placeholder="เช่น ถนนลาดพร้าว ปากซอย 71"
                  maxLength={255}
                />
              </div>

              <div>
                <label className="label" htmlFor="description">
                  รายละเอียดเพิ่มเติม
                </label>
                <textarea
                  id="description"
                  className="field"
                  rows={3}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="เช่น ท่วมเลนซ้าย 2 เลน รถเก๋งชิดขวาผ่านได้"
                  maxLength={2000}
                />
              </div>

              <div>
                <label className="label" htmlFor="photo">
                  รูปถ่ายจุดที่น้ำท่วม <span className="text-red-400">*</span>
                </label>
                <p className="mb-1.5 text-xs text-slate-400">
                  จำเป็นต้องมี — คนที่กำลังจะขับผ่านใช้รูปตัดสินใจ ไม่ใช่ตัวเลข
                  และรายงานที่มีรูปจะขึ้นแผนที่ทันทีโดยไม่ต้องรอตรวจ
                </p>
                <input
                  id="photo"
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={pickPhoto}
                  className="w-full text-sm text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-sm file:text-slate-200"
                />
                {photoPreview && (
                  <img
                    src={photoPreview}
                    alt="ตัวอย่างรูปที่เลือก"
                    className="mt-2 max-h-44 rounded-lg object-cover"
                  />
                )}
                <p className="mt-1 text-xs text-slate-500">
                  ระบบจะลบข้อมูล EXIF (รวมพิกัดกล้อง) ออกก่อนบันทึก
                </p>
              </div>

              <div>
                <label className="label" htmlFor="reporter">
                  ชื่อผู้แจ้ง (ไม่บังคับ)
                </label>
                <input
                  id="reporter"
                  className="field"
                  value={reporterName}
                  onChange={(event) => setReporterName(event.target.value)}
                  maxLength={128}
                />
              </div>

              {error && (
                <p className="rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
                  {error}
                </p>
              )}
            </div>

            <div className="sticky bottom-0 border-t border-slate-800 bg-slate-900/95 p-4 backdrop-blur">
              <button
                type="submit"
                className="btn-danger w-full disabled:opacity-50"
                disabled={busy || !photo || !point}
              >
                {busy ? 'กำลังส่ง…' : 'ส่งรายงาน'}
              </button>
              {!busy && (!photo || !point) && (
                <p className="mt-1.5 text-center text-xs text-slate-400">
                  ยัง{!point ? 'ไม่ได้ระบุตำแหน่ง' : ''}
                  {!point && !photo ? ' และ' : ''}
                  {!photo ? 'ไม่ได้แนบรูป' : ''}
                </p>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
