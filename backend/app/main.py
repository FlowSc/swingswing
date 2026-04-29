from contextlib import asynccontextmanager
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import bot, broker, trading
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.scan_worker import start_scan_worker, stop_scan_worker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logging.getLogger("app").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"SCAN_WORKER_BOOT scheduler_enabled={settings.scheduler_enabled}", flush=True)
    logging.getLogger(__name__).warning("Application startup: scheduler_enabled=%s", settings.scheduler_enabled)
    start_scan_worker()
    if settings.scheduler_enabled:
        start_scheduler()
    yield
    if settings.scheduler_enabled:
        stop_scheduler()
    await stop_scan_worker()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(broker.router)
app.include_router(bot.router)
app.include_router(trading.router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": settings.app_name, "environment": settings.environment}
