"""FastAPI application. Serves the API and, in production, the built SPA."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from .migrate import report_drift, sync_schema
from .models import utcnow
from .routers import (
    admin, auth, cameras, chat, imports, misc, reports, route_check, water_stations,
)
from .seed import run_seed

logger = logging.getLogger("floodwatch")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Where the built frontend lands inside the container image.
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create_all makes missing tables; sync_schema adds columns that were added
    # to a model after the table already existed. Together they cover every
    # additive change, which is all this app has needed so far.
    Base.metadata.create_all(bind=engine)
    added = sync_schema(engine)
    if added:
        logger.info("อัปเดตโครงสร้างฐานข้อมูล: %s", ", ".join(added))
    drift = report_drift(engine)
    if drift:
        logger.warning("พบคอลัมน์ในฐานข้อมูลที่ไม่มีในโมเดล (ไม่แตะต้อง): %s", drift)
    db = SessionLocal()
    try:
        run_seed(db)
        logger.info("seed complete")
    except Exception:
        logger.exception("seed failed — the app still starts, data may be incomplete")
    finally:
        db.close()

    os.makedirs(settings.upload_dir, exist_ok=True)

    boot_sync: asyncio.Task | None = None
    if settings.sync_stations_on_start:
        # Fire and forget. Awaiting this here would keep the app from serving
        # until every upstream answered: the Bangkok source alone walks ~300
        # station pages on a first run, which is minutes. A platform health
        # check times out long before that and restarts the container, so the
        # sync never finishes and the database stays empty — which is exactly
        # what happened on the first deploy.
        from .stations import sync_all

        async def _sync_in_background() -> None:
            db = SessionLocal()
            try:
                logger.info("เริ่มซิงก์สถานีเบื้องหลัง")
                logger.info("ซิงก์สถานีเสร็จ: %s", await sync_all(db))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ซิงก์สถานีตอนบูตล้มเหลว — แอปยังทำงานต่อได้")
            finally:
                db.close()

        # Keep the reference: a bare create_task can be garbage collected mid-run.
        boot_sync = asyncio.create_task(_sync_in_background())
    if settings.jwt_secret == "change-me-in-production":
        logger.warning("JWT_SECRET ยังเป็นค่าเริ่มต้น — ต้องตั้งค่าใหม่ก่อนใช้งานจริง")
    if "example.com" in settings.http_user_agent:
        # Nominatim answers such requests with 403, which silently breaks
        # place-name lookup, so say it out loud at boot.
        logger.warning(
            "HTTP_USER_AGENT ยังเป็นค่าตัวอย่าง (example.com) — Nominatim จะปฏิเสธคำขอ "
            "ให้ตั้งเป็นที่อยู่ติดต่อจริง ระหว่างนี้ระบบจะใช้ Photon เป็นตัวสำรอง")
    yield

    if boot_sync is not None and not boot_sync.done():
        boot_sync.cancel()
        try:
            await boot_sync
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(
    title=settings.app_name,
    description="เช็คน้ำท่วมบนเส้นทาง A→B จากกล้อง CCTV รายงานของผู้ใช้ และแชทบอท",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, reports.router, cameras.router, route_check.router,
               chat.router, misc.router, admin.router, imports.router,
               water_stations.router):
    app.include_router(router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "time": utcnow(),
        "routing_backend": settings.osrm_base_url,
        "chat_engine": "llm+rules" if settings.chat_llm_enabled else "rules",
        "moderation_required": settings.require_moderation,
    }


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Never leak a stack trace to a browser; log it in full instead."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"detail": "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่อีกครั้ง"})


# ---------------------------------------------------------------- static files

if os.path.isdir(settings.upload_dir):
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")),
              name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Serve the SPA, letting the client router own every non-API path.

        API routes are registered above and match first, so anything reaching
        here is either a real static file or a client-side route.
        """
        candidate = os.path.normpath(os.path.join(STATIC_DIR, full_path))
        # Guard against ../ escaping the static root.
        if candidate.startswith(os.path.abspath(STATIC_DIR)) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
