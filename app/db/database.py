"""SQLite asynchronous persistence for learning stats, rewards, and settings."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from app.learning.engine import FactRecord


DEFAULT_DB_PATH = Path("data/rewards.db")


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_connection(db_path: Path | str = DEFAULT_DB_PATH):
    """Ensure parent directory exists and yield SQLite connection with Row factory."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Initialize database tables and default configuration."""
    async with get_db_connection(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                factor_a INTEGER NOT NULL,
                factor_b INTEGER NOT NULL,
                box INTEGER DEFAULT 0,
                consecutive_correct INTEGER DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0,
                last_latency_ms REAL DEFAULT 0.0,
                avg_latency_ms REAL DEFAULT 0.0,
                last_seen REAL DEFAULT 0.0,
                PRIMARY KEY (factor_a, factor_b)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reward_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                minutes_awarded INTEGER NOT NULL,
                questions_answered INTEGER NOT NULL,
                synced_to_switch INTEGER DEFAULT 0,
                device_id TEXT,
                note TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Default settings if not already present
        defaults = {
            "questions_per_reward": "15",
            "minutes_per_reward": "5",
            "max_daily_reward_minutes": "60",
            "speed_threshold_ms": "4000.0",
            "retry_delay_questions": "3",
            "active_tables": json.dumps(list(range(2, 13))),
            "reward_mode": "bank",  # "bank" | "nintendo" | "hybrid"
            "bank_balance": "0",
            "bank_lifetime": "0",
            "exclude_tens": "false",
            "exclude_elevens_single_digit": "false",
            "exclude_elevens_two_digit": "false",
            "exclude_twos": "false",
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, v),
            )

        # Migrate previous settings to default 15 questions per 5 minutes reward
        await db.execute(
            "UPDATE settings SET value = '15' WHERE key = 'questions_per_reward' AND value IN ('8', '10')"
        )
        await db.execute(
            "UPDATE settings SET value = '5' WHERE key = 'minutes_per_reward' AND value IN ('6')"
        )
        await db.commit()


async def load_facts(db_path: Path | str = DEFAULT_DB_PATH) -> Dict[str, FactRecord]:
    """Load all fact mastery records from SQLite."""
    facts: Dict[str, FactRecord] = {}
    async with get_db_connection(db_path) as db:
        async with db.execute("SELECT * FROM facts") as cursor:
            async for row in cursor:
                key = f"{row['factor_a']}x{row['factor_b']}"
                facts[key] = FactRecord(
                    factor_a=row["factor_a"],
                    factor_b=row["factor_b"],
                    box=row["box"],
                    consecutive_correct=row["consecutive_correct"],
                    attempts=row["attempts"],
                    wrong_count=row["wrong_count"],
                    last_latency_ms=row["last_latency_ms"],
                    avg_latency_ms=row["avg_latency_ms"],
                    last_seen=row["last_seen"],
                )
    return facts


async def save_fact(fact: FactRecord, db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Save or update a single fact record."""
    async with get_db_connection(db_path) as db:
        await db.execute(
            """
            INSERT INTO facts (
                factor_a, factor_b, box, consecutive_correct,
                attempts, wrong_count, last_latency_ms, avg_latency_ms, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(factor_a, factor_b) DO UPDATE SET
                box = excluded.box,
                consecutive_correct = excluded.consecutive_correct,
                attempts = excluded.attempts,
                wrong_count = excluded.wrong_count,
                last_latency_ms = excluded.last_latency_ms,
                avg_latency_ms = excluded.avg_latency_ms,
                last_seen = excluded.last_seen
            """,
            (
                fact.factor_a,
                fact.factor_b,
                fact.box,
                fact.consecutive_correct,
                fact.attempts,
                fact.wrong_count,
                fact.last_latency_ms,
                fact.avg_latency_ms,
                fact.last_seen,
            ),
        )
        await db.commit()


async def get_setting(key: str, default: str = "", db_path: Path | str = DEFAULT_DB_PATH) -> str:
    """Retrieve a configuration value."""
    async with get_db_connection(db_path) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else default


async def set_setting(key: str, value: str, db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Save or update a configuration value."""
    async with get_db_connection(db_path) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings(db_path: Path | str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Retrieve all configuration values as typed dict."""
    async with get_db_connection(db_path) as db:
        async with db.execute("SELECT key, value FROM settings") as cursor:
            rows = await cursor.fetchall()
            raw = {row["key"]: row["value"] for row in rows}

    return {
        "questions_per_reward": int(raw.get("questions_per_reward", 15)),
        "minutes_per_reward": int(raw.get("minutes_per_reward", 5)),
        "max_daily_reward_minutes": int(raw.get("max_daily_reward_minutes", 60)),
        "speed_threshold_ms": float(raw.get("speed_threshold_ms", 4000.0)),
        "retry_delay_questions": int(raw.get("retry_delay_questions", 3)),
        "active_tables": json.loads(raw.get("active_tables", json.dumps(list(range(2, 13))))),
        "reward_mode": raw.get("reward_mode", "nintendo"),
        "bank_balance": int(raw.get("bank_balance", 0)),
        "bank_lifetime": int(raw.get("bank_lifetime", 0)),
        "exclude_tens": str(raw.get("exclude_tens", "false")).lower() == "true",
        "exclude_elevens_single_digit": str(raw.get("exclude_elevens_single_digit", raw.get("exclude_elevens_two_digit", "false"))).lower() == "true",
        "exclude_elevens_two_digit": str(raw.get("exclude_elevens_single_digit", raw.get("exclude_elevens_two_digit", "false"))).lower() == "true",
        "exclude_twos": str(raw.get("exclude_twos", "false")).lower() == "true",
    }


async def get_bank_balance(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Return currently available banked screen time minutes."""
    val = await get_setting("bank_balance", "0", db_path)
    return int(val) if val.lstrip("-").isdigit() else 0


async def adjust_bank_minutes(minutes: int, reason: str = "", db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Add or deduct minutes from the screen time bank. Returns new balance."""
    current = await get_bank_balance(db_path)
    new_balance = max(0, current + minutes)
    await set_setting("bank_balance", str(new_balance), db_path)

    if minutes > 0:
        lifetime = int(await get_setting("bank_lifetime", "0", db_path))
        await set_setting("bank_lifetime", str(lifetime + minutes), db_path)

    return new_balance


async def record_reward_event(
    minutes: int,
    questions: int,
    synced: bool,
    device_id: Optional[str] = None,
    note: str = "",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """Record a reward claim in history."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    async with get_db_connection(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO reward_events (timestamp, minutes_awarded, questions_answered, synced_to_switch, device_id, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_iso, minutes, questions, 1 if synced else 0, device_id, note),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def get_today_rewarded_minutes(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Calculate the total reward minutes claimed today (UTC)."""
    today_start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    async with get_db_connection(db_path) as db:
        async with db.execute(
            "SELECT SUM(minutes_awarded) as total FROM reward_events WHERE timestamp LIKE ? AND synced_to_switch = 1",
            (f"{today_start}%",),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["total"] or 0) if row else 0


async def get_recent_rewards(limit: int = 10, db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve recent reward history."""
    async with get_db_connection(db_path) as db:
        async with db.execute(
            "SELECT * FROM reward_events ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def reset_today_rewards(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Clear reward events recorded today so the daily reward cap is refreshed."""
    today_start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    async with get_db_connection(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM reward_events WHERE timestamp LIKE ?",
            (f"{today_start}%",),
        )
        await db.commit()
        return cursor.rowcount


async def reset_bank_balance(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Reset the screen time bank balance to 0."""
    await set_setting("bank_balance", "0", db_path)
    await record_reward_event(
        minutes=0,
        questions=0,
        synced=False,
        note="Screen Time Bank balance reset to 0",
        db_path=db_path,
    )
    return 0

