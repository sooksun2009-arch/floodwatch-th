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
import { LEVELS, SITUATIONS, levelLabel, safePhotoUrl, timeAgo } from '../api'

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
  onError,
  pickMode = false,
  fitKey = null,
  className = '',
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const readyRef = useRef(false)
  const markersRef = useRef({ origin: null, destination: null })
  // Callbacks live in a ref so the map's event handlers always see the latest
  // ones without the map having to be torn down and rebuilt.
  const handlersRef = useRef({ onCameraClick, onMapClick, onError })
  handlersRef.current = { onCameraClick, onMapClick, onError }

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
    map.on('error', (event) => {
      const message = event?.error?.message || 'แผนที่ทำงานผิดพลาด'
      // Tile fetch hiccups are transient and not worth alarming anyone over.
      if (/tile|fetch|abort|network/i.test(message)) return
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
      if (props.depth) line(`วัดได้ ${props.depth} ซม.`, 'color:#94a3b8')
      line(`ยืนยัน ${props.confirms} · แย้ง ${props.disputes}`, 'color:#94a3b8')
      line(props.age, 'color:#64748b;margin-top:.25rem')

      // Only same-origin upload paths are rendered; an absolute URL from a
      // report could otherwise point anywhere, including a javascript: scheme.
      const photo = safePhotoUrl(props.photo)
      if (photo) {
        const image = document.createElement('img')
        image.src = photo
        image.alt = 'ภาพจุดน้ำท่วม'
        image.loading = 'lazy'
        image.style.cssText = 'margin-top:.5rem;border-radius:.5rem;width:100%'
        root.appendChild(image)
      }

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

      popup.setLngLat(event.lngLat).setDOMContent(root).addTo(map)
    })

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
