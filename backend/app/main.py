from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import get_password_hash
from app.models import AdminUser
from app.routers import auth, invoices, shares, tags


app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)

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


@app.on_event("startup")
def on_startup() -> None:
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


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(invoices.router, prefix=settings.api_prefix)
app.include_router(tags.router, prefix=settings.api_prefix)
app.include_router(shares.router, prefix=settings.api_prefix)
app.include_router(shares.log_router, prefix=settings.api_prefix)
app.include_router(shares.public_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
