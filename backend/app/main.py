from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import get_password_hash
from app.models import AdminUser, ShareAccessLog
from app.routers import auth, invoices, shares, tags


app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)
_share_log_cleanup_task: asyncio.Task | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list if settings.cors_origin_list else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _wait_for_db_ready() -> None:
    max_retries = settings.startup_db_max_retries
    retry_seconds = settings.startup_db_retry_seconds

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database is ready after %s attempt(s).", attempt)
            return
        except OperationalError as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"Database not ready after {max_retries} attempts.") from exc
            logger.warning(
                "Database not ready (attempt %s/%s). Retry in %ss. Error: %s",
                attempt,
                max_retries,
                retry_seconds,
                exc,
            )
            time.sleep(retry_seconds)


def _cleanup_expired_share_logs() -> None:
    retention_days = max(1, settings.share_log_retention_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    db = SessionLocal()
    try:
        result = db.execute(delete(ShareAccessLog).where(ShareAccessLog.created_at < cutoff))
        db.commit()
        deleted_count = int(result.rowcount or 0)
        if deleted_count > 0:
            logger.info("Cleaned %s expired share access logs before %s.", deleted_count, cutoff.isoformat())
    except Exception:
        logger.exception("Failed to cleanup expired share access logs.")
        db.rollback()
    finally:
        db.close()


async def _share_log_cleanup_worker() -> None:
    interval_hours = max(1, settings.share_log_cleanup_interval_hours)
    interval_seconds = interval_hours * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        _cleanup_expired_share_logs()


@app.on_event("startup")
async def on_startup() -> None:
    global _share_log_cleanup_task
    settings.ensure_dirs()
    _wait_for_db_ready()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = db.scalar(select(AdminUser).where(AdminUser.username == settings.bootstrap_admin_username))
        bootstrap_hash = get_password_hash(settings.bootstrap_admin_password)
        if not admin:
            db.add(
                AdminUser(
                    username=settings.bootstrap_admin_username,
                    password_hash=bootstrap_hash,
                    is_active=True,
                )
            )
            db.commit()
        elif not admin.password_hash.startswith("$pbkdf2-sha256$"):
            # Migrate legacy password hashes to pbkdf2_sha256 to avoid bcrypt backend compatibility issues.
            admin.password_hash = bootstrap_hash
            db.add(admin)
            db.commit()
    finally:
        db.close()

    _cleanup_expired_share_logs()
    if _share_log_cleanup_task is None or _share_log_cleanup_task.done():
        _share_log_cleanup_task = asyncio.create_task(_share_log_cleanup_worker())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _share_log_cleanup_task
    if _share_log_cleanup_task is None:
        return
    _share_log_cleanup_task.cancel()
    try:
        await _share_log_cleanup_task
    except asyncio.CancelledError:
        pass
    finally:
        _share_log_cleanup_task = None


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(invoices.router, prefix=settings.api_prefix)
app.include_router(tags.router, prefix=settings.api_prefix)
app.include_router(shares.router, prefix=settings.api_prefix)
app.include_router(shares.log_router, prefix=settings.api_prefix)
app.include_router(shares.public_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
