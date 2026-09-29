// Colour per depth band of a flooded road (Floodboard data), shared by the
// map layer and the legend. Its own module so the legend, which loads with the
// page, does not pull in the map library, which loads later.
export const FLOOD_ROAD_BANDS = [
  ['closed', '#7f1d1d'],
  ['30', '#dc2626'],
  ['20', '#f59e0b'],
  ['10', '#2563eb'],
  ['lt10', '#38bdf8'],
  ['unknown', '#94a3b8'],
]
