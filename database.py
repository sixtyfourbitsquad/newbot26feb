"""Async PostgreSQL layer using asyncpg pool."""
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the global connection pool; create if needed."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        logger.info("Database pool created")
    return _pool


@asynccontextmanager
async def acquire():
    """Acquire a connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def init_db() -> None:
    """Create tables if they do not exist."""
    async with acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
                last_active TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
                is_blocked BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id SERIAL PRIMARY KEY,
                started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
                total INT NOT NULL DEFAULT 0,
                success INT NOT NULL DEFAULT 0,
                failed INT NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running'
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS forward_mapping (
                admin_chat_id BIGINT NOT NULL,
                admin_message_id INT NOT NULL,
                user_telegram_id BIGINT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
                PRIMARY KEY (admin_chat_id, admin_message_id)
            );
        """)
        logger.info("Database schema initialized")


async def close_pool() -> None:
    """Close the global connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


# --- Users ---


async def upsert_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    async with acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username, first_name, joined_at, last_active)
            VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_active = NOW() AT TIME ZONE 'UTC'
        """, telegram_id, username, first_name)


async def update_last_active(telegram_id: int) -> None:
    async with acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_active = NOW() AT TIME ZONE 'UTC' WHERE telegram_id = $1",
            telegram_id,
        )


async def set_user_blocked(telegram_id: int, blocked: bool = True) -> None:
    async with acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_blocked = $1 WHERE telegram_id = $2",
            blocked,
            telegram_id,
        )


async def get_all_active_user_ids() -> list[int]:
    """Return telegram_id of all users where is_blocked = FALSE."""
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT telegram_id FROM users WHERE is_blocked = FALSE"
        )
        return [r["telegram_id"] for r in rows]


async def get_stats() -> dict[str, int]:
    """Return total users, active (last 7 days), blocked count."""
    async with acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        active = await conn.fetchval("""
            SELECT COUNT(*) FROM users
            WHERE last_active >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '7 days'
        """)
        blocked = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE is_blocked = TRUE"
        )
        return {
            "total": total or 0,
            "active_7d": active or 0,
            "blocked": blocked or 0,
        }


async def cleanup_blocked_users() -> int:
    """Delete users where is_blocked = TRUE. Returns deleted count."""
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE is_blocked = TRUE")
        # "DELETE N" -> extract N
        return int(result.split()[-1]) if result else 0


# --- Settings ---


async def get_setting(key: str) -> Any | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = $1", key
        )
        return row["value"] if row else None


async def set_setting(key: str, value: Any) -> None:
    json_value = value if isinstance(value, str) else json.dumps(value)
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ($1, $2::jsonb) ON CONFLICT (key) DO UPDATE SET value = $2::jsonb",
            key,
            json_value,
        )


# --- Forward mapping (admin message -> user) ---


async def save_forward_mapping(
    admin_chat_id: int,
    admin_message_id: int,
    user_telegram_id: int,
) -> None:
    async with acquire() as conn:
        await conn.execute("""
            INSERT INTO forward_mapping (admin_chat_id, admin_message_id, user_telegram_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (admin_chat_id, admin_message_id) DO UPDATE SET
                user_telegram_id = EXCLUDED.user_telegram_id,
                created_at = NOW() AT TIME ZONE 'UTC'
        """, admin_chat_id, admin_message_id, user_telegram_id)


async def get_user_from_reply(
    admin_chat_id: int,
    admin_message_id: int,
) -> int | None:
    async with acquire() as conn:
        row = await conn.fetchrow("""
            SELECT user_telegram_id FROM forward_mapping
            WHERE admin_chat_id = $1 AND admin_message_id = $2
        """, admin_chat_id, admin_message_id)
        return row["user_telegram_id"] if row else None


# --- Broadcasts ---


async def create_broadcast(total: int) -> int:
    """Create a broadcast record; returns id."""
    async with acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO broadcasts (total, status) VALUES ($1, 'running')
            RETURNING id
        """, total)
        return row["id"]


async def update_broadcast(
    broadcast_id: int,
    success: int,
    failed: int,
    status: str = "completed",
) -> None:
    async with acquire() as conn:
        await conn.execute("""
            UPDATE broadcasts SET success = $1, failed = $2, status = $3
            WHERE id = $4
        """, success, failed, status, broadcast_id)
