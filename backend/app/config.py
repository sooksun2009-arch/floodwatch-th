"""Runtime configuration. Everything overridable by env var (Railway-friendly)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FloodWatch TH"
    # Railway injects DATABASE_URL for the attached Postgres service.
    database_url: str = "sqlite:///./floodwatch.db"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 72

    # A report stops showing on the map this long after it was filed, unless
    # someone re-confirms it. Flood water moves; stale pins are worse than none.
    report_ttl_hours: int = 12
    # Disputes needed to pull an approved report back into the moderation queue.
    auto_flag_disputes: int = 3
    # Anonymous reports per IP per hour.
    anon_report_limit: int = 5
    chat_limit_per_hour: int = 60

    # Reports from unauthenticated visitors go live only after a moderator
    # approves them. Set false for a closed/internal deployment.
    require_moderation: bool = True
    allow_anonymous_reports: bool = True
    # A photo is the difference between a claim and evidence. Without one a
    # report can carry no place, no name and no picture and still reach the
    # map, which is what teaches people to stop trusting it. It also collapses
    # the moderation queue: a report with a photo goes live on its own, so
    # requiring one means nothing waits for a human who is asleep.
    # Officials and moderators are exempt — their reports are already vouched
    # for, and they file from desks as well as from roadsides.
    require_photo: bool = True
    # A pin with no name is a dot the next person cannot check against
    # anything they can see from the car. Reports were arriving this way and
    # showing on the map as "ไม่ระบุจุด". Officials are exempt, as with photos:
    # their imports carry their own identifiers.
    require_place: bool = True

    # --- Automatic approval ---
    # A queue guarded by one person fails at exactly the wrong moment: the night
    # it floods is the night reports arrive fastest and the moderator is asleep,
    # and a report nobody can see helps nobody. These two rules let a report go
    # live on its own when the evidence is strong enough that holding it back
    # costs more than it protects. Set both false to require a human every time.
    #
    # The asymmetry that justifies this: a flood pin that turns out to be wrong
    # costs a driver a detour, while a real one held in a queue can send them
    # into water they cannot see the depth of.
    auto_approve_with_photo: bool = True
    auto_approve_corroborated: bool = True
    # How close and how recent another person's report must be to count as
    # corroboration. 300 m keeps it to the same stretch of road rather than the
    # neighbourhood, and 6 hours is short enough that the water has probably not
    # drained in between.
    auto_approve_radius_m: int = 300
    auto_approve_window_hours: int = 6

    # --- Route checking (the primary feature) ---
    # Any OSRM-compatible server. The public demo host is fine for development
    # but rate-limited and not for production — self-host osrm-backend with a
    # Thailand OSM extract, or point this at GraphHopper's OSRM-compatible API.
    osrm_base_url: str = "https://router.project-osrm.org"
    routing_timeout_sec: float = 8.0

    # OpenRouteService is optional but adds the one thing OSRM cannot do:
    # routing that actively steers around flooded areas (avoid_polygons),
    # instead of merely ranking the alternatives OSRM happened to return.
    # Free API key: https://openrouteservice.org/dev/#/signup
    ors_api_key: str = ""
    ors_base_url: str = "https://api.openrouteservice.org"
    # Radius of the no-go circle drawn around each impassable report.
    avoid_radius_m: int = 120
    # Only reports at or above this level are routed around. Steering a driver
    # kilometres out of their way to dodge a puddle is worse than the puddle.
    avoid_min_level: str = "deep"
    # How far from the route a flood pin still counts as "on my way".
    # 150 m covers the far side of a dual carriageway without pulling in the
    # parallel soi one block over.
    route_corridor_m: int = 150
    # Cameras get a wider corridor: a camera 400 m away still shows you the
    # water on the road you are about to take.
    route_camera_corridor_m: int = 600
    # Reports below this confidence are shown but do not drive the verdict.
    route_min_confidence: float = 0.25

    # Place-name lookup for "จากบางนาไปรามคำแหง". Tries the local gazetteer
    # (provinces, districts, reported places, camera names) first and only then
    # the external geocoder.
    geocode_enabled: bool = True
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    # Fallback geocoder, used when Nominatim declines or is rate limited.
    photon_base_url: str = "https://photon.komoot.io"
    # Nominatim's usage policy requires a real identifying User-Agent.
    http_user_agent: str = "FloodWatchTH/1.0 (flood alert app; contact: admin@example.com)"

    # --- Canal/river gauges (คลังข้อมูลน้ำแห่งชาติ) ---
    # Instrument readings that refresh every ~10 minutes nationwide. Used as a
    # separate map layer and as supporting context for route verdicts.
    thaiwater_base_url: str = "https://api-v3.thaiwater.net"
    # สำนักการระบายน้ำ กทม. — ~300 canal gauges inside Bangkok, where ThaiWater
    # has only three. No JSON API, so the department's own pages are parsed.
    bma_water_base_url: str = "https://weather.bangkok.go.th/water"
    # Coordinates come from one page per station and never change, so they are
    # fetched a few at a time until every station has them.
    bma_detail_per_sync: int = 60
    bma_detail_delay_sec: float = 0.4
    sync_bma_on_start: bool = True
    station_timeout_sec: float = 30.0
    # A reading older than this is shown as stale instead of current.
    station_stale_hours: int = 6
    # Sync on boot so a fresh deploy has live data without waiting for a cron.
    sync_stations_on_start: bool = True
    # Keep syncing on this interval from inside the app. Doing it in-process
    # avoids needing an external scheduler and an API token just to keep water
    # levels current. 0 syncs once at boot and then stops.
    station_sync_interval_min: int = 15
    # A camera frame older than this marks the camera "stale" — agency snapshot
    # endpoints keep returning HTTP 200 long after the picture stops updating.
    camera_stale_minutes: int = 90

    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 8
    max_image_px: int = 1600

    # --- Photo storage ---
    # Unset means the container's own filesystem, which on a host with no
    # persistent disk means every deploy deletes every photo ever uploaded.
    # Fill these in and photos go to any S3-compatible bucket instead, where
    # they outlive the container. Two that work:
    #
    #   Supabase Storage (no card required)
    #     endpoint:    https://<project ref>.supabase.co/storage/v1/s3
    #     region:      the project's region, e.g. ap-southeast-1 — required,
    #                  because the signature is computed over it
    #     public base: https://<ref>.supabase.co/storage/v1/object/public/<bucket>
    #
    #   Cloudflare R2
    #     endpoint:    https://<account id>.r2.cloudflarestorage.com
    #     region:      auto
    #     public base: the bucket's r2.dev URL, or a custom domain
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = ""
    s3_public_base_url: str = ""
    # R2 accepts "auto"; most other providers sign against a real region and
    # reject the request outright if it does not match theirs.
    s3_region: str = "auto"

    # Optional: let Claude phrase the chatbot answer from retrieved facts.
    # Off by default — the deterministic engine answers without any API credit.
    chat_llm_enabled: bool = False
    anthropic_api_key: str = ""
    chat_llm_model: str = "claude-haiku-4-5-20251001"

    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin1234"
    # Break-glass: set this to reset the admin password on the next boot, then
    # remove it. Changing SEED_ADMIN_PASSWORD does nothing once the account
    # exists — deliberately, so a restart never silently rewrites credentials —
    # which otherwise leaves a forgotten password locking the operator out of
    # their own deployment for good.
    admin_password_reset: str = ""
    seed_demo_data: bool = True

    cors_origins: str = "*"

    # --- Rain radar and forecast (Longdo Weather) ---
    # Unset leaves every rain feature off and the rest of the app unchanged.
    # Free key from api.longdo.com/console. Calls are proxied through this app
    # rather than made from the page, so the key stays on the server.
    longdo_api_key: str = ""
    longdo_weather_base_url: str = "https://weather.longdo.com"
    rain_timeout_sec: float = 10.0
    # The radar itself refreshes about every ten minutes, so anything shorter
    # spends quota to receive the same picture.
    rain_cache_sec: int = 300
    # Tiles are cached longer than that: a radar frame is the same picture for
    # its whole ten-minute life, and tiles are what exhausts the quota.
    rain_tile_cache_sec: int = 600
    # Width of the band around a route that counts as "on the way". Wider than
    # the flood corridor on purpose: a storm two kilometres up the road will be
    # over it shortly, while a flood two kilometres away will not.
    rain_corridor_km: float = 4.0
    # How many points along a route get their own forecast call, and how far
    # each one looks around itself. Every sample is a request, so this trades
    # resolution against quota.
    rain_forecast_samples: int = 3
    rain_forecast_radius_km: float = 10.0
    # How near a traffic camera has to be to count as "rain on this route",
    # used when the area query is unavailable. Generous, because a camera is a
    # single point standing in for the weather around it.
    rain_camera_km: float = 8.0

    # Upstream allows 60 requests a minute and 5,000 a day across the whole
    # key. Map tiles can spend that in minutes — one pan with the radar on is
    # dozens of requests — and when they do, every other call gets a 403 as
    # well. That happened: the radar took the cameras and the forecast down
    # with it. So tiles and everything else draw from separate budgets, and
    # both stay under the real ceiling.
    rain_rate_per_min: int = 40
    rain_tiles_per_min: int = 24
    rain_tiles_per_day: int = 2500
    rain_services_per_day: int = 1500

    # --- Satellite flood extent (GISTDA Disaster Platform) ---
    # Where the water actually was, seen from orbit, as opposed to where
    # someone reported it or where a canal gauge stands. Unset leaves the whole
    # layer off and the app unchanged. Key from api-gateway.gistda.or.th; it
    # travels in an "API-Key" header, and is proxied through this app so the
    # page never sees it.
    #
    # This is an area observation up to a day old, not a statement about any
    # road. It stays its own map layer with its own caption and is never folded
    # into a route verdict — the same rule the canal gauges live under.
    gistda_api_key: str = ""
    gistda_base_url: str = "https://api-gateway.gistda.or.th/api/2.0/resources"
    # Which product the map layer draws. 1day is the freshest and the emptiest;
    # 7days is the useful default during a wet week, because a road that was
    # under water on Tuesday is worth knowing about on Thursday.
    gistda_product: str = "7days"
    gistda_timeout_sec: float = 15.0
    # Six hours. These products are rebuilt at most daily, so a shorter life
    # spends quota to receive a byte-identical picture. The radar's ten minutes
    # is the wrong number here and copying it would have been the easy mistake.
    gistda_tile_cache_sec: int = 21600
    # Unpublished quota, so the daily figure stays conservative -- with a six
    # hour cache, repeat views of the same area cost nothing anyway.
    #
    # The per-minute figure is a floor, not a safety margin, and 60 was still
    # a floor set below the floor: production reported 60/60 spent with 60/2000
    # used for the day, which is one screenful and then a blank layer. A
    # retina viewport with the map's tile buffer asks for far more than the
    # 25 the arithmetic suggested.
    #
    # The daily figure is the real guard, and the six hour cache means looking
    # at the same area again costs nothing, so the minute can be generous.
    gistda_tiles_per_min: int = 240
    gistda_tiles_per_day: int = 2000
    # Past this the tiles subdivide without getting sharper — four times the
    # requests per level for the same picture.
    gistda_max_zoom: int = 12

    # The GeoJSON side, used to steer routes around observed water. It takes no
    # query parameters, so there is no way to ask for one province -- the whole
    # country arrives or nothing does. Hence a hard ceiling on the download and
    # its own small daily budget: this is a big fetch, not a tile.
    gistda_features_cache_sec: int = 10800
    gistda_features_per_day: int = 200
    # The whole country is about 14 MB, so 12 refused the real dataset and the
    # layer quietly did nothing. Raised past it with room to grow, and the
    # outlines are coarsened as they are read rather than kept at full
    # resolution -- on a 512 MB instance the parsed structure, not the
    # download, is what would end the process.
    gistda_max_download_mb: float = 24.0
    # How many flood areas may be handed to the routing engine at once, and how
    # coarsely their outlines are rounded first. ORS rejects avoid_polygons that
    # are too many or too intricate, and it rejects the whole request rather
    # than the offending shape -- so a route that could have been steered around
    # water comes back as no route at all.
    gistda_avoid_max_polygons: int = 30
    gistda_avoid_grid_deg: float = 0.002
    # How close observed water has to be to the road before it is worth saying
    # anything. The published outlines turn out to be many small patches -- one
    # sampled was about twenty metres across -- so asking whether the route
    # passes *inside* one almost never fires: the path is sampled far more
    # coarsely than that. Distance to the patch is the question that matches
    # the data. Tighter than the rain corridor (4 km) because this is water on
    # the ground, and a field flooded a kilometre away says nothing about a road.
    gistda_route_corridor_km: float = 0.3
    # Whether a route runs through observed water is decided by reading the
    # same picture the visitor sees, at this zoom. The GeoJSON was the first
    # attempt and it cannot answer the question: the feed has no way to ask for
    # one region, the whole of it is too large to parse here, and the truncated
    # page turned out to cover only the north -- so routes through the worst
    # flooding in the country, around Ayutthaya, saw nothing at all.
    #
    # Tiles have none of those problems. They cover everywhere, they are
    # already budgeted and cached for six hours, and what raises the flag is
    # exactly what is drawn on screen.
    gistda_route_zoom: int = 12
    # Points sampled along the route. Most fall in the same few tiles, so this
    # costs far less than it looks.
    gistda_route_samples: int = 24
    # How opaque a pixel has to be before it counts as water rather than the
    # feathered edge of a shape.
    gistda_route_alpha: int = 40
    # How many flood areas to ask for in one request. The Swagger lists no
    # parameters, but the feed returned exactly ten outlines for the whole
    # country -- which is the OGC default page size, not a dry country. Asking
    # explicitly is the difference between the first page and the data.
    # Asking for everything at once came back "Query param 'limit' is invalid":
    # the feed has a cap and does not say what it is. So this is a ladder --
    # the first value that is accepted wins, and the truncation warning still
    # fires if the answer arrives exactly full, because a page boundary and a
    # dry country look identical from here.
    gistda_features_limit: int = 20000
    gistda_features_limit_fallbacks: str = "10000,5000,1000"

    # Shared secret for POST /api/stations/bma/ingest. The Bangkok drainage
    # site refuses connections from outside Thailand, so the container cannot
    # reach it and a relay that can has to push the readings in instead. Unset
    # leaves the endpoint closed.
    ingest_token: str = ""

    # Shared secret that lets a scheduled job (keepalive.gs) download the CSV
    # exports without a moderator login. Unset = only a signed-in moderator
    # can export. Separate from INGEST_TOKEN so a leak of one does not open
    # the other.
    backup_token: str = ""

    # Flooded road segments from Floodboard's open data (CC BY 4.0). Fetched
    # at most once per cache period for everyone, never per visitor.
    floodroads_enabled: bool = True
    floodroads_url: str = "https://floodboard.org/api/export/roads.geojson"
    floodroads_cache_sec: int = 300
    # Shown on the map from this confidence up; below it is mostly guesswork.
    floodroads_min_conf_show: float = 0.3
    # Only from this confidence up may a segment call a route risky/blocked.
    floodroads_min_conf_block: float = 0.5
    # How close a segment's points must be to the route to run "along" it.
    floodroads_near_m: int = 30


def _safe_header(value: str, fallback: str) -> str:
    """Make a config string safe to send as an HTTP header value.

    HTTP headers are latin-1 only. A Thai character, a stray newline or a tab
    in HTTP_USER_AGENT makes h11 reject the request with LocalProtocolError —
    and because that header goes on *every* outbound call, one bad character
    silently takes down routing, geocoding and the gauge sync at once. That is
    exactly what happened on the first production deploy, and no value an
    operator types into a dashboard should be able to do it.
    """
    cleaned = " ".join((value or "").split())  # collapse newlines/tabs
    try:
        cleaned.encode("latin-1")
    except UnicodeEncodeError:
        cleaned = cleaned.encode("ascii", "ignore").decode("ascii").strip()
    return cleaned or fallback


DEFAULT_USER_AGENT = "FloodWatchTH/1.0 (flood alert app)"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.http_user_agent = _safe_header(s.http_user_agent, DEFAULT_USER_AGENT)
    # Railway/Heroku hand out postgres:// which SQLAlchemy 2 no longer accepts.
    if s.database_url.startswith("postgres://"):
        s.database_url = s.database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif s.database_url.startswith("postgresql://"):
        s.database_url = s.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return s


settings = get_settings()
