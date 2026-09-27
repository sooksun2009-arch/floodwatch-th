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
