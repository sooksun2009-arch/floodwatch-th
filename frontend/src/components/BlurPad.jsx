import { useEffect, useRef, useState } from 'react'

/**
 * Tap the photo to blur a spot -- a licence plate, a house number, a face the
 * server might miss -- before it is sent.
 *
 * Done here, on the phone, so the part someone chose to hide never leaves the
 * device. Faces are also blurred automatically on the server; plates are not,
 * because no small detector reads Thai plates reliably, and a check that
 * misses half of them would promise something it does not do.
 *
 * Pixelation rather than canvas `filter: blur()`: the filter is missing from
 * older Safari, which is most of the phones this will be used on.
 */
const MAX_PX = 1600 // the server keeps no more than this anyway

// Average the spot down to a handful of cells, then stretch it back smoothly.
// Few cells whatever the spot's size: at ten per side a plate's characters
// were still half legible. Smooth rather than blocky upscaling, so there are
// no hard cell edges either -- the result is a soft smear with nothing in it.
function pixelate(ctx, x, y, w, h) {
  const tmp = document.createElement('canvas')
  tmp.width = 6
  tmp.height = 3
  const small = tmp.getContext('2d')
  small.imageSmoothingEnabled = true
  small.imageSmoothingQuality = 'high'
  small.drawImage(ctx.canvas, x, y, w, h, 0, 0, 6, 3)
  ctx.save()
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(tmp, 0, 0, 6, 3, x, y, w, h)
  ctx.restore()
}

/** A spot is its centre as fractions of the image, so it survives resizing. */
function spotRect(spot, width, height) {
  const base = Math.min(width, height) * spot.size
  const w = base * 2 // plates are wide
  const h = base
  return [
    Math.max(0, spot.x * width - w / 2),
    Math.max(0, spot.y * height - h / 2),
    Math.min(w, width),
    Math.min(h, height),
  ]
}

export function renderBlurred(image, spots) {
  const scale = Math.min(1, MAX_PX / Math.max(image.naturalWidth, image.naturalHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(image.naturalWidth * scale)
  canvas.height = Math.round(image.naturalHeight * scale)
  const ctx = canvas.getContext('2d')
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  for (const spot of spots) {
    const [x, y, w, h] = spotRect(spot, canvas.width, canvas.height)
    pixelate(ctx, x, y, w, h)
  }
  return canvas
}

export default function BlurPad({ src, spots, onSpots, onImage }) {
  const canvasRef = useRef(null)
  const [image, setImage] = useState(null)
  const [size, setSize] = useState(0.08)

  useEffect(() => {
    const img = new Image()
    img.onload = () => {
      setImage(img)
      onImage?.(img)
    }
    img.src = src
  }, [src])

  useEffect(() => {
    if (!image || !canvasRef.current) return
    const drawn = renderBlurred(image, spots)
    const canvas = canvasRef.current
    canvas.width = drawn.width
    canvas.height = drawn.height
    canvas.getContext('2d').drawImage(drawn, 0, 0)
  }, [image, spots])

  const tap = (event) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const x = (event.clientX - rect.left) / rect.width
    const y = (event.clientY - rect.top) / rect.height
    if (x < 0 || x > 1 || y < 0 || y > 1) return
    onSpots([...spots, { x, y, size }])
  }

  return (
    <div className="mt-2">
      <canvas
        ref={canvasRef}
        onClick={tap}
        role="img"
        aria-label="รูปที่เลือก แตะเพื่อเบลอจุดที่ไม่อยากให้เห็น"
        className="max-h-60 max-w-full cursor-crosshair rounded-lg"
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-400">👆 แตะรูปเพื่อเบลอป้ายทะเบียน/บ้านเลขที่</span>
        <span className="flex overflow-hidden rounded-lg border border-slate-700">
          {[['เล็ก', 0.05], ['กลาง', 0.08], ['ใหญ่', 0.14]].map(([label, value]) => (
            <button
              key={label}
              type="button"
              onClick={() => setSize(value)}
              aria-pressed={size === value}
              className={`px-2 py-0.5 ${size === value ? 'bg-slate-700 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
            >
              {label}
            </button>
          ))}
        </span>
        {spots.length > 0 && (
          <button
            type="button"
            onClick={() => onSpots(spots.slice(0, -1))}
            className="rounded-lg border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
          >
            ↶ ย้อน ({spots.length})
          </button>
        )}
      </div>
    </div>
  )
}
