import { useEffect, useRef, useState } from 'react'
import { levelLabel, timeAgo } from '../api'

// Turn a YouTube watch/short/live link into its embed form.
const youtubeEmbed = (url) => {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/live\/|youtube\.com\/embed\/)([\w-]{6,})/,
  ]
  for (const pattern of patterns) {
    const match = url.match(pattern)
    if (match) return `https://www.youtube.com/embed/${match[1]}?autoplay=1&mute=1`
  }
  return url
}

function HlsPlayer({ src, onError }) {
  const videoRef = useRef(null)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined
    let hls = null
    let cancelled = false

    // Safari (and iOS in particular) plays HLS natively; everywhere else needs
    // Media Source Extensions via hls.js, which is loaded only when a camera
    // actually uses HLS.
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = src
      video.play().catch(() => {})
      return () => {
        video.removeAttribute('src')
        video.load()
      }
    }

    import('hls.js')
      .then(({ default: Hls }) => {
        if (cancelled) return
        if (!Hls.isSupported()) {
          onError('เบราว์เซอร์นี้เล่นสตรีม HLS ไม่ได้')
          return
        }
        hls = new Hls({ lowLatencyMode: true, liveDurationInfinity: true })
        hls.loadSource(src)
        hls.attachMedia(video)
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (!data.fatal) return
          // Recover once from each fatal class before giving up, since live
          // streams drop segments routinely.
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad()
          else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError()
          else onError('เชื่อมต่อสตรีมไม่สำเร็จ')
        })
      })
      .catch(() => onError('โหลดตัวเล่นวิดีโอไม่สำเร็จ'))

    return () => {
      cancelled = true
      hls?.destroy()
    }
  }, [src, onError])

  return (
    <video
      ref={videoRef}
      className="h-full w-full bg-black object-contain"
      muted
      playsInline
      autoPlay
      controls
    />
  )
}

function SnapshotPlayer({ cameraId, refreshSec, onError }) {
  const [tick, setTick] = useState(0)
  const [stamp, setStamp] = useState(null)

  useEffect(() => {
    const period = Math.max(3, refreshSec || 15) * 1000
    const timer = setInterval(() => setTick((value) => value + 1), period)
    return () => clearInterval(timer)
  }, [refreshSec])

  // Always fetched through our own proxy: the upstream endpoints usually send
  // no CORS headers and check Referer, so a direct browser request fails.
  const src = `/api/cameras/${cameraId}/snapshot?t=${tick}`

  return (
    <div className="relative h-full w-full bg-black">
      <img
        key={src}
        src={src}
        alt="ภาพจากกล้องวงจรปิด"
        className="h-full w-full object-contain"
        onLoad={() => setStamp(new Date())}
        onError={() => onError('ดึงภาพจากกล้องไม่สำเร็จ — กล้องอาจออฟไลน์อยู่')}
      />
      {stamp && (
        <div className="absolute bottom-2 right-2 rounded-lg bg-black/70 px-2 py-1 text-xs text-slate-200">
          อัปเดต {stamp.toLocaleTimeString('th-TH')}
        </div>
      )}
    </div>
  )
}

export default function CameraModal({ camera, onClose, onReportHere }) {
  const [error, setError] = useState(null)

  useEffect(() => {
    setError(null)
  }, [camera?.id])

  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!camera) return null

  const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${camera.lat},${camera.lng}`

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="card w-full max-w-3xl overflow-hidden rounded-b-none sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`ภาพจากกล้อง ${camera.name}`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 p-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-bold">{camera.name}</h3>
            <p className="mt-0.5 text-sm text-slate-400">
              {[camera.owner_org, camera.district, camera.province_name]
                .filter(Boolean)
                .join(' · ') || 'ไม่ระบุหน่วยงาน'}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {camera.is_demo && (
                <span className="chip bg-amber-500/15 text-amber-300">สตรีมตัวอย่าง ไม่ใช่ภาพจริง</span>
              )}
              {camera.frame_age_minutes > 90 && (
                <span className="chip bg-amber-500/15 text-amber-300">
                  ภาพล่าสุด {timeAgo(camera.frame_age_minutes)} — ไม่ใช่ภาพสด
                </span>
              )}
              {camera.nearby_flood_level && (
                <span className="chip bg-red-500/15 text-red-300">
                  ใกล้จุดน้ำท่วม: {levelLabel(camera.nearby_flood_level)}
                </span>
              )}
              {camera.distance_km != null && (
                <span className="chip bg-slate-800 text-slate-300">
                  ห่าง {camera.distance_km} กม.
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-2xl leading-none text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            aria-label="ปิด"
          >
            ×
          </button>
        </div>

        <div className="aspect-video w-full bg-black">
          {error ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
              <p className="text-sm text-slate-300">{error}</p>
              <button className="btn-ghost text-sm" onClick={() => setError(null)}>
                ลองใหม่
              </button>
            </div>
          ) : camera.stream_type === 'hls' ? (
            <HlsPlayer src={camera.stream_url} onError={setError} />
          ) : camera.stream_type === 'snapshot' || camera.stream_type === 'mjpeg' ? (
            <SnapshotPlayer
              cameraId={camera.id}
              refreshSec={camera.refresh_sec}
              onError={setError}
            />
          ) : (
            <iframe
              title={camera.name}
              src={
                camera.stream_type === 'youtube'
                  ? youtubeEmbed(camera.stream_url)
                  : camera.stream_url
              }
              className="h-full w-full border-0"
              allow="autoplay; encrypted-media; picture-in-picture"
              allowFullScreen
              referrerPolicy="no-referrer"
              sandbox="allow-scripts allow-same-origin allow-presentation"
            />
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 p-4">
          <button className="btn-danger text-sm" onClick={() => onReportHere?.(camera)}>
            เห็นน้ำท่วมในภาพ — แจ้งจุดนี้
          </button>
          <a className="btn-ghost text-sm" href={mapsUrl} target="_blank" rel="noreferrer">
            เปิดใน Google Maps
          </a>
          {camera.source_page && (
            <a className="btn-ghost text-sm" href={camera.source_page} target="_blank" rel="noreferrer">
              หน้าต้นทาง
            </a>
          )}
          {camera.notes && (
            <p className="w-full text-xs leading-relaxed text-slate-500">{camera.notes}</p>
          )}
        </div>
      </div>
    </div>
  )
}
