from __future__ import annotations

import logging

from sqlalchemy import Engine, text


logger = logging.getLogger(__name__)


def run_migrations(engine: Engine, *, default_user_id: int) -> None:
    """
    Lightweight in-place migrations without Alembic.

    Goals:
    - Add user_id columns for multi-tenant isolation.
    - Backfill existing rows to default user.
    - Adjust tags uniqueness to be per-user.
    - Add share.mode/share.filters to support dynamic shares.
    """
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_user_id ON invoices (user_id)"))

        conn.execute(text("ALTER TABLE tags ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_user_id ON tags (user_id)"))

        conn.execute(text("ALTER TABLE shares ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shares_user_id ON shares (user_id)"))

        conn.execute(text("ALTER TABLE shares ADD COLUMN IF NOT EXISTS mode VARCHAR(20) NOT NULL DEFAULT 'static'"))
        conn.execute(text("ALTER TABLE shares ADD COLUMN IF NOT EXISTS filters JSONB"))

        # Backfill existing data to default user.
        conn.execute(text("UPDATE invoices SET user_id = :uid WHERE user_id IS NULL"), {"uid": default_user_id})
        conn.execute(text("UPDATE tags SET user_id = :uid WHERE user_id IS NULL"), {"uid": default_user_id})
        conn.execute(text("UPDATE shares SET user_id = :uid WHERE user_id IS NULL"), {"uid": default_user_id})

        # Enforce non-null user_id for isolation.
        conn.execute(text("ALTER TABLE invoices ALTER COLUMN user_id SET NOT NULL"))
        conn.execute(text("ALTER TABLE tags ALTER COLUMN user_id SET NOT NULL"))
        conn.execute(text("ALTER TABLE shares ALTER COLUMN user_id SET NOT NULL"))

        # Add foreign keys if missing.
        conn.execute(
            text(
                """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_invoices_user_id') THEN
        ALTER TABLE invoices
        ADD CONSTRAINT fk_invoices_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;
"""
            )
        )
        conn.execute(
            text(
                """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tags_user_id') THEN
        ALTER TABLE tags
        ADD CONSTRAINT fk_tags_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;
"""
            )
        )
        conn.execute(
            text(
                """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shares_user_id') THEN
        ALTER TABLE shares
        ADD CONSTRAINT fk_shares_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;
"""
            )
        )

        # Make tags uniqueness per user (PostgreSQL default constraint name is usually tags_name_key).
        # Safe to run even if it does not exist.
        conn.execute(text("ALTER TABLE tags DROP CONSTRAINT IF EXISTS tags_name_key"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_tags_user_name ON tags (user_id, name)"))

    logger.info("Migrations completed.")
