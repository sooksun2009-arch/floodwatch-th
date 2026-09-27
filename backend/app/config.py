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
    # A camera frame older than this marks the camera "stale" — agency snapshot
    # endpoints keep returning HTTP 200 long after the picture stops updating.
    camera_stale_minutes: int = 90

    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 8
    max_image_px: int = 1600

    # Optional: let Claude phrase the chatbot answer from retrieved facts.
    # Off by default — the deterministic engine answers without any API credit.
    chat_llm_enabled: bool = False
    anthropic_api_key: str = ""
    chat_llm_model: str = "claude-haiku-4-5-20251001"

    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin1234"
    seed_demo_data: bool = True

    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Railway/Heroku hand out postgres:// which SQLAlchemy 2 no longer accepts.
    if s.database_url.startswith("postgres://"):
        s.database_url = s.database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif s.database_url.startswith("postgresql://"):
        s.database_url = s.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return s


settings = get_settings()
