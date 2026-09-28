import { useEffect, useRef } from 'react'
// maplibre-gl 6 removed the default export; import the classes by name.
import {
  GeolocateControl,
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from 'maplibre-gl'
// maplibre resolves its worker as new URL('./maplibre-gl-worker.mjs', <its own
// module url>). After bundling, that path does not exist, the worker 404s, and
// every GeoJSON layer silently renders nothing while the raster basemap still
// draws — a map with no pins and no error. Let the bundler emit the worker (it
// is a module worker that imports maplibre's shared chunk) and hand maplibre
// the real URL.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

setWorkerUrl(maplibreWorkerUrl)
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  LEVELS, SITUATIONS, api, levelLabel, reportAge, safePhotoUrl, timeAgo,
} from '../api'

// Raster OpenStreetMap tiles need no API key, which keeps the app free to run.
// For production traffic, point VITE_MAP_STYLE at a tile provider you have an
// agreement with — the OSM community tile servers are not for heavy use.
const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© ผู้ร่วมสร้าง OpenStreetMap',
    },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0f172a' } },
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      // Dim and desaturate the basemap so the flood colours carry the meaning.
      paint: { 'raster-brightness-max': 0.82, 'raster-saturation': -0.35, 'raster-contrast': 0.05 },
    },
  ],
}

const STYLE_URL = import.meta.env.VITE_MAP_STYLE || null

const VERDICT_COLOR = {
  clear: '#10b981',
  caution: '#eab308',
  risky: '#f97316',
  blocked: '#dc2626',
}

const emptyFC = { type: 'FeatureCollection', features: [] }

const reportsToGeoJSON = (reports) => ({
  type: 'FeatureCollection',
  features: (reports || []).map((r) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [r.lng, r.lat] },
    properties: {
      id: r.id,
      level: r.level,
      place: r.place || r.district || r.province_name || 'ไม่ระบุจุด',
      label: r.level_label || levelLabel(r.level),
      depth: r.depth_cm ?? '',
      confirms: r.confirm_count ?? 0,
      disputes: r.dispute_count ?? 0,
      age: timeAgo(r.age_minutes),
      ageMinutes: r.age_minutes ?? '',
      source: r.source,
      photo: r.photo_url || '',
      critical: r.level === 'severe' || r.level === 'closed' ? 1 : 0,
    },
  })),
})

const camerasToGeoJSON = (cameras) => ({
  type: 'FeatureCollection',
  features: (cameras || []).map((c) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [c.lng, c.lat] },
    properties: { id: c.id, name: c.name, demo: c.is_demo ? 1 : 0, org: c.owner_org || '' },
  })),
})

// Gauges are drawn as diamonds so they never read as a road-flood pin — they
// are a different kind of fact (an instrument in a canal, not water on tarmac).
const stationsToGeoJSON = (stations) => ({
  type: 'FeatureCollection',
  features: (stations || []).map((s) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
    properties: {
      id: s.id,
      name: s.name,
      situation: s.situation_level ?? 0,
      label: s.situation_label || '',
      diff: s.diff_from_bank ?? '',
      agency: s.agency || '',
      area: [s.amphoe_name, s.province_name].filter(Boolean).join(' · '),
      stale: s.is_stale ? 1 : 0,
      overflowing: s.is_overflowing ? 1 : 0,
    },
  })),
})

const TREND_COLOR = {
  rising: '#f59e0b',
  falling: '#34d399',
  steady: '#94a3b8',
}

const SVG_NS = 'http://www.w3.org/2000/svg'

// A gap longer than this means the gauge stopped reporting, so the line is
// broken there. Joining across it would draw a smooth climb the water may not
// have made — the reading either side is real, the slope between them is not.
const GAP_HOURS = 2

/** Tiny time-accurate chart of the readings. Returns null if there is nothing to draw. */
const sparkline = (points, direction) => {
  const usable = (points || []).filter((p) => typeof p.value === 'number')
  if (usable.length < 2) return null

  const width = 176
  const height = 40
  const pad = 3
  const times = usable.map((p) => new Date(p.at).getTime())
  const values = usable.map((p) => p.value)
  const t0 = times[0]
  const tSpan = times[times.length - 1] - t0 || 1
  const min = Math.min(...values)
  const span = Math.max(...values) - min || 1

  const x = (t) => pad + ((t - t0) / tSpan) * (width - pad * 2)
  const y = (v) => height - pad - ((v - min) / span) * (height - pad * 2)

  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('width', String(width))
  svg.setAttribute('height', String(height))
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
  svg.style.cssText = 'display:block;margin:.3rem 0'

  const stroke = TREND_COLOR[direction] || TREND_COLOR.steady
  let run = []
  const flush = () => {
    if (run.length > 1) {
      const line = document.createElementNS(SVG_NS, 'polyline')
      line.setAttribute('points', run.join(' '))
      line.setAttribute('fill', 'none')
      line.setAttribute('stroke', stroke)
      line.setAttribute('stroke-width', '1.6')
      line.setAttribute('stroke-linejoin', 'round')
      line.setAttribute('stroke-linecap', 'round')
      svg.appendChild(line)
    }
    run = []
  }

  usable.forEach((point, index) => {
    if (index > 0 && times[index] - times[index - 1] > GAP_HOURS * 3600 * 1000) flush()
    run.push(`${x(times[index]).toFixed(1)},${y(point.value).toFixed(1)}`)
  })
  flush()

  const last = document.createElementNS(SVG_NS, 'circle')
  last.setAttribute('cx', x(times[times.length - 1]).toFixed(1))
  last.setAttribute('cy', y(values[values.length - 1]).toFixed(1))
  last.setAttribute('r', '2.4')
  last.setAttribute('fill', stroke)
  svg.appendChild(last)
  return svg
}

const routesToGeoJSON = (routes) => ({
  type: 'FeatureCollection',
  features: (routes || [])
    .filter((r) => r.path?.length > 1)
    .map((r, index) => ({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: r.path.map(([lat, lng]) => [lng, lat]) },
      properties: {
        color: VERDICT_COLOR[r.verdict] || '#38bdf8',
        primary: index === 0 ? 1 : 0,
        dashed: r.is_straight_line ? 1 : 0,
      },
    })),
})

// Level colours as a MapLibre "match" expression, sourced from the same table
// the legend and verdict card read.
const levelMatch = [
  'match',
  ['get', 'level'],
  ...Object.entries(LEVELS).flatMap(([key, value]) => [key, value.color]),
  '#64748b',
]

const situationMatch = [
  'match',
  ['get', 'situation'],
  ...Object.entries(SITUATIONS).flatMap(([key, value]) => [Number(key), value.color]),
  '#64748b',
]

export default function MapView({
  reports = [],
  cameras = [],
  stations = [],
  routes = [],
  origin = null,
  destination = null,
  onCameraClick,
  onMapClick,
  onCenterChange,
  onError,
  pickMode = false,
  showRadar = false,
  fitKey = null,
  className = '',
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const readyRef = useRef(false)
  // Identifies the popup a pending history request belongs to, so a slow reply
  // cannot write last station's trend into the one now on screen.
  const historyTokenRef = useRef(null)
  // Pins this visitor has already voted on, so reopening one does not invite a
  // second vote. The server allows changing a vote; this is only about not
  // asking again.
  const votedReportsRef = useRef(new Set())
  const markersRef = useRef({ origin: null, destination: null })
  // Callbacks live in a ref so the map's event handlers always see the latest
  // ones without the map having to be torn down and rebuilt.
  const handlersRef = useRef({ onCameraClick, onMapClick, onCenterChange, onError })
  handlersRef.current = { onCameraClick, onMapClick, onCenterChange, onError }

  useEffect(() => {
    if (mapRef.current) return undefined

    const map = new MapLibreMap({
      container: containerRef.current,
      style: STYLE_URL || OSM_STYLE,
      center: [100.5018, 13.7563],
      zoom: 10,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    // Handle for the smoke test to ask the map what it actually rendered.
    // Reading the canvas back does not work after the frame is composited, so
    // querying the map is the only reliable check. Opt-in outside dev.
    if (import.meta.env.DEV || window.location.search.includes('__smoke=1')) {
      window.__fwMap = map
    }

    // A map that fails to build its layers renders as an empty basemap and
    // says nothing — the worst way for a flood map to fail. Report it.
    // Sources whose failure must never reach the screen. The radar is context
    // a visitor opted into; the flood data is the point of the page. An
    // optional layer shouting over the map is worse than that layer missing.
    const OPTIONAL_SOURCES = new Set(['radar'])

    map.on('error', (event) => {
      if (OPTIONAL_SOURCES.has(event?.sourceId)) return
      const message = event?.error?.message || 'แผนที่ทำงานผิดพลาด'
      // Matched on the message as well, because a source id does not always
      // survive: the radar's 503 arrived as "AJAXError: (503): <url>", which
      // the old filter — tile|fetch|abort|network — let straight through onto
      // a red banner across the flood map.
      if (/tile|fetch|abort|network|ajaxerror|\/api\/rain\//i.test(message)) return
      handlersRef.current.onError?.(message)
    })

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(
      new GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true,
      }),
      'top-right',
    )

    map.on('load', () => {
      try {
      map.addSource('reports', { type: 'geojson', data: emptyFC })
      map.addSource('cameras', { type: 'geojson', data: emptyFC })
      map.addSource('stations', { type: 'geojson', data: emptyFC })
      map.addSource('routes', { type: 'geojson', data: emptyFC })

      // Rain radar, served through our own API so the upstream key stays on
      // the server. Added once and toggled by visibility rather than added and
      // removed, so flipping it off and on does not refetch every tile.
      map.addSource('radar', {
        type: 'raster',
        tiles: [`${window.location.origin}/api/rain/radar/{z}/{x}/{y}.png`],
        tileSize: 256,
        // Radar covers Thailand only; asking for tiles beyond it wastes quota
        // to be told there is nothing there.
        bounds: [97.2, 5.4, 105.7, 20.6],
        // Below this a single tile spans continents and the radar has nothing
        // to put in it; the map asked for 0/0/0 — the whole world — and got a
        // failure that surfaced as an error banner over the flood map.
        minzoom: 5,
        // Stop requesting new tiles past zoom 9 and stretch these instead.
        // The radar's own resolution is about a kilometre, so sharper tiles
        // carry no more information — and each zoom level past this asks for
        // four times as many. Zoom 12 emptied the daily quota in one session
        // and every other rain call started failing with it.
        maxzoom: 9,
      })
      map.addLayer({
        id: 'radar-layer',
        type: 'raster',
        source: 'radar',
        layout: { visibility: 'none' },
        // Rain sits above the basemap but under every pin and route line:
        // it is context, never the thing being read.
        paint: { 'raster-opacity': 0.55 },
      })

      // Route lines sit under the pins so markers stay clickable.
      map.addLayer({
        id: 'route-casing',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#0f172a',
          'line-width': ['case', ['==', ['get', 'primary'], 1], 11, 8],
          'line-opacity': 0.9,
        },
      })
      // Two layers rather than one: line-dasharray is not a data-driven paint
      // property in MapLibre, so the dashed (straight-line estimate) case has
      // to be its own layer selected by a filter.
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'dashed'], 0],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['case', ['==', ['get', 'primary'], 1], 6, 4],
          'line-opacity': ['case', ['==', ['get', 'primary'], 1], 1, 0.55],
        },
      })
      map.addLayer({
        id: 'route-line-estimate',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'dashed'], 1],
        layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 5,
          'line-opacity': 0.85,
          'line-dasharray': [2, 1.8],
        },
      })

      // Gauges sit below the road-flood pins: they are context, not the answer.
      map.addLayer({
        id: 'station-dots',
        type: 'circle',
        source: 'stations',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            7, ['case', ['==', ['get', 'overflowing'], 1], 5, 3],
            13, ['case', ['==', ['get', 'overflowing'], 1], 10, 6],
          ],
          'circle-color': situationMatch,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#0f172a',
          'circle-opacity': ['case', ['==', ['get', 'stale'], 1], 0.35, 0.95],
        },
      })

      map.addLayer({
        id: 'camera-dots',
        type: 'circle',
        source: 'cameras',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 5, 14, 9],
          'circle-color': '#0ea5e9',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#e0f2fe',
          'circle-opacity': ['case', ['==', ['get', 'demo'], 1], 0.6, 1],
        },
      })

      map.addLayer({
        id: 'report-halo',
        type: 'circle',
        source: 'reports',
        filter: ['==', ['get', 'critical'], 1],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 14, 14, 26],
          'circle-color': '#dc2626',
          'circle-opacity': 0.18,
        },
      })
      map.addLayer({
        id: 'report-dots',
        type: 'circle',
        source: 'reports',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 7, 14, 13],
          'circle-color': levelMatch,
          'circle-stroke-width': 2,
          'circle-stroke-color': '#0f172a',
        },
      })

      readyRef.current = true
      } catch (err) {
        // Without this the failure is invisible: the exception escapes the
        // listener, the remaining layers are never added, and the map just
        // sits there empty.
        handlersRef.current.onError?.(`สร้างชั้นข้อมูลบนแผนที่ไม่สำเร็จ: ${err.message}`)
      }
    })

    const popup = new Popup({ closeButton: true, offset: 14, maxWidth: '270px' })

    map.on('click', 'report-dots', (event) => {
      const props = event.features?.[0]?.properties
      if (!props) return

      // Popup content is built with DOM nodes and textContent, never an HTML
      // string: place names and descriptions are attacker-controllable (anyone
      // can file a report), so nothing from a feature is ever parsed as markup.
      const root = document.createElement('div')
      root.style.cssText = 'font-size:13px;line-height:1.5'

      const line = (text, css) => {
        if (!text && text !== 0) return
        const node = document.createElement('div')
        node.textContent = String(text)
        if (css) node.style.cssText = css
        root.appendChild(node)
      }

      line(props.place, 'font-weight:700;margin-bottom:.15rem')
      line(props.label, `color:${LEVELS[props.level]?.color || '#94a3b8'};font-weight:600`)

      // Directly under the level rather than last and dimmest. On a road that
      // changes within the hour, how old the report is decides whether the
      // level above it still means anything — a reader put it better than I
      // would: knowing when it came in is what makes them willing to drive.
      const age = props.ageMinutes === '' ? null : reportAge(Number(props.ageMinutes))
      if (age) {
        line(age.text, `color:${age.color};font-weight:600;margin-top:.1rem`)
        if (age.note) line(age.note, `color:${age.color};opacity:.85;font-size:12px`)
      }

      if (props.depth) line(`วัดได้ ${props.depth} ซม.`, 'color:#94a3b8')
      const counts = document.createElement('div')
      counts.textContent = `ยืนยัน ${props.confirms} · แย้ง ${props.disputes}`
      counts.style.cssText = 'color:#94a3b8'
      root.appendChild(counts)

      // Only same-origin upload paths are rendered; an absolute URL from a
      // report could otherwise point anywhere, including a javascript: scheme.
      const photo = safePhotoUrl(props.photo)
      if (photo) {
        const image = document.createElement('img')
        image.src = photo
        image.alt = 'ภาพจุดน้ำท่วม'
        image.loading = 'lazy'
        // Cap the height. A portrait photo — which is most phone photos —
        // renders at full aspect ratio otherwise, and the popup grows until
        // the buttons under it are off the bottom of the screen. The picture
        // is there to judge the depth, not to be viewed full size.
        image.style.cssText =
          'margin-top:.5rem;border-radius:.5rem;width:100%;max-height:160px;' +
          'object-fit:cover;cursor:zoom-in'
        image.title = 'แตะเพื่อเปิดรูปเต็ม'
        image.addEventListener('click', () => window.open(photo, '_blank', 'noopener'))
        root.appendChild(image)
      }

      // Until now these buttons lived only in the route results panel, so
      // anyone who found a pin by looking at the map — most people — could see
      // that a road was flooded three hours ago and had no way to say the
      // water had gone. A stale pin sends drivers around a road that is fine,
      // and the people best placed to clear it are the ones standing there.
      const actions = document.createElement('div')
      actions.style.cssText = 'display:flex;gap:.4rem;margin-top:.5rem;flex-wrap:wrap'
      const buttonCss =
        'border:1px solid #334155;border-radius:.5rem;padding:.25rem .55rem;' +
        'font-size:12px;color:#cbd5e1;background:transparent;cursor:pointer'

      const said = document.createElement('span')
      said.style.cssText = 'font-size:12px;color:#34d399;align-self:center'

      const castVote = (choice, button) => {
        for (const node of actions.querySelectorAll('button')) node.disabled = true
        api
          .voteReport(props.id, choice)
          .then((updated) => {
            votedReportsRef.current.add(props.id)
            counts.textContent =
              `ยืนยัน ${updated.confirm_count} · แย้ง ${updated.dispute_count}`
            said.textContent = choice === 'dispute'
              ? 'ขอบคุณครับ — จะตรวจสอบให้'
              : 'ขอบคุณครับ'
          })
          .catch((error) => {
            for (const node of actions.querySelectorAll('button')) node.disabled = false
            said.style.color = '#f59e0b'
            said.textContent = error?.message || 'ส่งไม่สำเร็จ ลองใหม่อีกครั้ง'
          })
      }

      for (const [text, choice] of [['ยังท่วมอยู่', 'confirm'], ['น้ำลดแล้ว', 'dispute']]) {
        const button = document.createElement('button')
        button.type = 'button'
        button.textContent = text
        button.style.cssText = buttonCss
        button.addEventListener('click', () => castVote(choice, button))
        actions.appendChild(button)
      }
      actions.appendChild(said)

      if (votedReportsRef.current.has(props.id)) {
        for (const node of actions.querySelectorAll('button')) node.disabled = true
        said.textContent = 'ขอบคุณครับ'
      }
      root.appendChild(actions)

      popup.setLngLat(event.lngLat).setDOMContent(root).addTo(map)
    })

    map.on('click', 'station-dots', (event) => {
      const props = event.features?.[0]?.properties
      if (!props) return

      const root = document.createElement('div')
      root.style.cssText = 'font-size:13px;line-height:1.5'
      const line = (text, css) => {
        if (!text && text !== 0) return
        const node = document.createElement('div')
        node.textContent = String(text)
        if (css) node.style.cssText = css
        root.appendChild(node)
      }
      line(props.name, 'font-weight:700;margin-bottom:.15rem')
      line(props.label, `color:${SITUATIONS[props.situation]?.color || '#94a3b8'};font-weight:600`)
      if (props.diff !== '' && props.diff !== null) {
        const over = Number(props.diff)
        line(
          over > 0
            ? `สูงกว่าตลิ่ง ${over.toFixed(2)} ม.`
            : `ต่ำกว่าตลิ่ง ${Math.abs(over).toFixed(2)} ม.`,
          'color:#94a3b8',
        )
      }
      line(props.area, 'color:#94a3b8')
      line(props.agency ? `ข้อมูลโดย ${props.agency}` : '', 'color:#64748b;margin-top:.25rem')
      if (props.stale === 1) line('ข้อมูลไม่อัปเดต', 'color:#f59e0b;margin-top:.25rem')

      // A level on its own does not say whether to turn around — the same
      // number means opposite things depending on which way it is going. The
      // history is a separate request, so the popup opens now and fills in.
      const slot = document.createElement('div')
      slot.style.cssText = 'margin-top:.4rem;color:#64748b'
      slot.textContent = 'กำลังดูแนวโน้ม…'
      root.appendChild(slot)

      const token = Symbol('station-history')
      historyTokenRef.current = token
      api
        .stationHistory(props.id)
        .then((data) => {
          // Another pin was clicked, or this popup closed, while we waited.
          if (historyTokenRef.current !== token || !slot.isConnected) return
          slot.textContent = ''
          if (!data.available) {
            slot.textContent = data.reason || 'ไม่มีข้อมูลย้อนหลัง'
            return
          }
          const chart = sparkline(data.points, data.trend?.direction)
          if (chart) slot.appendChild(chart)
          if (data.trend) {
            const label = document.createElement('div')
            label.textContent = data.trend.label
            label.style.cssText =
              `color:${TREND_COLOR[data.trend.direction] || TREND_COLOR.steady};font-weight:600`
            slot.appendChild(label)
          }
        })
        .catch(() => {
          if (historyTokenRef.current !== token || !slot.isConnected) return
          slot.textContent = 'ดูแนวโน้มไม่สำเร็จ'
        })

      popup.setLngLat(event.lngLat).setDOMContent(root).addTo(map)
    })

    // Where the crosshair is pointing. moveend rather than move: the centre
    // only has to be right at the moment someone taps confirm, and they have
    // to stop panning to do that.
    const reportCentre = () => {
      const centre = map.getCenter()
      handlersRef.current.onCenterChange?.({ lat: centre.lat, lng: centre.lng })
    }
    reportCentre()
    map.on('moveend', reportCentre)

    map.on('click', 'camera-dots', (event) => {
      const id = event.features?.[0]?.properties?.id
      if (id) handlersRef.current.onCameraClick?.(id)
    })

    map.on('click', (event) => {
      // Ignore clicks that landed on a pin; those have their own handlers.
      const hits = map.queryRenderedFeatures(event.point, {
        layers: ['report-dots', 'camera-dots', 'station-dots'],
      })
      if (hits.length === 0) {
        handlersRef.current.onMapClick?.({ lat: event.lngLat.lat, lng: event.lngLat.lng })
      }
    })

    for (const layer of ['report-dots', 'camera-dots', 'station-dots']) {
      map.on('mouseenter', layer, () => {
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', layer, () => {
        map.getCanvas().style.cursor = pickMode ? 'crosshair' : ''
      })
    }

    return () => {
      map.remove()
      mapRef.current = null
      readyRef.current = false
    }
  }, [])

  // Keep the cursor in sync with pick mode without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const canvas = map.getCanvas()
    if (canvas) canvas.style.cursor = pickMode ? 'crosshair' : ''
  }, [pickMode])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !readyRef.current || !map.getLayer('radar-layer')) return
    map.setLayoutProperty('radar-layer', 'visibility', showRadar ? 'visible' : 'none')
  }, [showRadar])

  // Push data into the sources whenever it changes, waiting for style load.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return undefined

    const apply = () => {
      map.getSource('reports')?.setData(reportsToGeoJSON(reports))
      map.getSource('cameras')?.setData(camerasToGeoJSON(cameras))
      map.getSource('stations')?.setData(stationsToGeoJSON(stations))
      map.getSource('routes')?.setData(routesToGeoJSON(routes))
    }

    if (readyRef.current) {
      apply()
      return undefined
    }
    // The style is still loading; the sources do not exist yet.
    map.once('load', apply)
    return () => map.off('load', apply)
  }, [reports, cameras, stations, routes])

  // Origin / destination pins.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const place = (key, point, color, labelText) => {
      const current = markersRef.current[key]
      if (!point) {
        current?.remove()
        markersRef.current[key] = null
        return
      }
      if (current) {
        current.setLngLat([point.lng, point.lat])
        return
      }
      const el = document.createElement('div')
      el.style.cssText = `width:30px;height:30px;border-radius:50% 50% 50% 4px;transform:rotate(-45deg);
        background:${color};border:2px solid #f8fafc;display:flex;align-items:center;justify-content:center;
        box-shadow:0 3px 10px rgb(0 0 0 / .45)`
      el.innerHTML = `<span style="transform:rotate(45deg);font-weight:700;font-size:13px;color:#fff">${labelText}</span>`
      markersRef.current[key] = new Marker({ element: el, anchor: 'bottom' })
        .setLngLat([point.lng, point.lat])
        .addTo(map)
    }

    place('origin', origin, '#0ea5e9', 'A')
    place('destination', destination, '#f43f5e', 'B')
  }, [origin, destination])

  // Fit the viewport to whatever is currently meaningful.
  useEffect(() => {
    const map = mapRef.current
    if (!map || fitKey == null) return undefined

    const run = () => {
      const points = []
      routes.forEach((r) => r.path?.forEach(([lat, lng]) => points.push([lng, lat])))
      if (origin) points.push([origin.lng, origin.lat])
      if (destination) points.push([destination.lng, destination.lat])
      if (points.length === 0) reports.forEach((r) => points.push([r.lng, r.lat]))
      if (points.length === 0) return

      if (points.length === 1) {
        map.easeTo({ center: points[0], zoom: 14 })
        return
      }
      const bounds = points.reduce(
        (acc, point) => acc.extend(point),
        new LngLatBounds(points[0], points[0]),
      )
      map.fitBounds(bounds, { padding: { top: 70, bottom: 70, left: 50, right: 50 }, maxZoom: 15 })
    }

    if (readyRef.current) {
      run()
      return undefined
    }
    map.once('load', run)
    return () => map.off('load', run)
  }, [fitKey])

  return <div ref={containerRef} className={className} />
}
