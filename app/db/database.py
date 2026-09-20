"""Plain JSON asynchronous persistence for learning stats, rewards, and settings."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.learning.engine import FactRecord

DEFAULT_DB_PATH = Path("data/rewards.json")

_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_lock(path_str: str) -> asyncio.Lock:
    if path_str not in _LOCKS:
        _LOCKS[path_str] = asyncio.Lock()
    return _LOCKS[path_str]


DEFAULT_SETTINGS: Dict[str, str] = {
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


def _migrate_from_sqlite_if_exists(json_path: Path) -> Optional[Dict[str, Any]]:
    """If json_path doesn't exist, check for a legacy SQLite rewards.db to migrate."""
    candidates = [
        json_path.with_suffix(".db"),
        json_path.parent / "rewards.db",
    ]
    for sqlite_file in candidates:
        if sqlite_file.exists() and sqlite_file != json_path:
            try:
                conn = sqlite3.connect(sqlite_file)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                facts: Dict[str, Any] = {}
                try:
                    cursor.execute("SELECT * FROM facts")
                    for row in cursor.fetchall():
                        key = f"{row['factor_a']}x{row['factor_b']}"
                        facts[key] = {
                            "factor_a": row["factor_a"],
                            "factor_b": row["factor_b"],
                            "box": row["box"],
                            "consecutive_correct": row["consecutive_correct"],
                            "attempts": row["attempts"],
                            "wrong_count": row["wrong_count"],
                            "last_latency_ms": row["last_latency_ms"],
                            "avg_latency_ms": row["avg_latency_ms"],
                            "last_seen": row["last_seen"],
                        }
                except Exception:
                    pass

                settings: Dict[str, str] = dict(DEFAULT_SETTINGS)
                try:
                    cursor.execute("SELECT key, value FROM settings")
                    for row in cursor.fetchall():
                        settings[row["key"]] = str(row["value"])
                except Exception:
                    pass

                events: List[Dict[str, Any]] = []
                try:
                    cursor.execute("SELECT * FROM reward_events ORDER BY id ASC")
                    for row in cursor.fetchall():
                        events.append({
                            "id": row["id"],
                            "timestamp": row["timestamp"],
                            "minutes_awarded": row["minutes_awarded"],
                            "questions_answered": row["questions_answered"],
                            "synced_to_switch": row["synced_to_switch"],
                            "device_id": row["device_id"],
                            "note": row["note"],
                        })
                except Exception:
                    pass

                conn.close()
                return {
                    "facts": facts,
                    "settings": settings,
                    "reward_events": events,
                }
            except Exception:
                pass
    return None


def _read_data_sync(path: Path) -> Dict[str, Any]:
    if not path.exists():
        migrated = _migrate_from_sqlite_if_exists(path)
        if migrated:
            _write_data_sync(path, migrated)
            return migrated

        data: Dict[str, Any] = {
            "facts": {},
            "settings": dict(DEFAULT_SETTINGS),
            "reward_events": [],
        }
        _write_data_sync(path, data)
        return data

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                data = {}
    except Exception:
        data = {}

    data.setdefault("facts", {})
    data.setdefault("settings", {})
    data.setdefault("reward_events", [])

    for k, v in DEFAULT_SETTINGS.items():
        if k not in data["settings"]:
            data["settings"][k] = v

    return data


def _write_data_sync(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as tf:
        json.dump(data, tf, indent=2)
        temp_name = tf.name
    os.replace(temp_name, path)


async def _read_data(db_path: Path | str) -> Dict[str, Any]:
    path = Path(db_path)
    lock = _get_lock(str(path.resolve()))
    async with lock:
        return await asyncio.to_thread(_read_data_sync, path)


async def _update_data(db_path: Path | str, modifier) -> Any:
    path = Path(db_path)
    lock = _get_lock(str(path.resolve()))
    async with lock:
        data = await asyncio.to_thread(_read_data_sync, path)
        result = modifier(data)
        await asyncio.to_thread(_write_data_sync, path, data)
        return result


async def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Initialize JSON data store and default configuration."""
    def _init(data: Dict[str, Any]):
        settings = data.setdefault("settings", {})
        for k, v in DEFAULT_SETTINGS.items():
            if k not in settings:
                settings[k] = v
        # Migrate previous settings to default 15 questions per 5 minutes
        if settings.get("questions_per_reward") in ("8", "10"):
            settings["questions_per_reward"] = "15"
        if settings.get("minutes_per_reward") == "6":
            settings["minutes_per_reward"] = "5"

    await _update_data(db_path, _init)


async def load_facts(db_path: Path | str = DEFAULT_DB_PATH) -> Dict[str, FactRecord]:
    """Load all fact mastery records from JSON."""
    data = await _read_data(db_path)
    facts: Dict[str, FactRecord] = {}
    for key, row in data.get("facts", {}).items():
        facts[key] = FactRecord(
            factor_a=row["factor_a"],
            factor_b=row["factor_b"],
            box=row.get("box", 0),
            consecutive_correct=row.get("consecutive_correct", 0),
            attempts=row.get("attempts", 0),
            wrong_count=row.get("wrong_count", 0),
            last_latency_ms=float(row.get("last_latency_ms", 0.0)),
            avg_latency_ms=float(row.get("avg_latency_ms", 0.0)),
            last_seen=float(row.get("last_seen", 0.0)),
        )
    return facts


async def save_fact(fact: FactRecord, db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Save or update a single fact record."""
    def _save(data: Dict[str, Any]):
        key = f"{fact.factor_a}x{fact.factor_b}"
        data.setdefault("facts", {})[key] = {
            "factor_a": fact.factor_a,
            "factor_b": fact.factor_b,
            "box": fact.box,
            "consecutive_correct": fact.consecutive_correct,
            "attempts": fact.attempts,
            "wrong_count": fact.wrong_count,
            "last_latency_ms": fact.last_latency_ms,
            "avg_latency_ms": fact.avg_latency_ms,
            "last_seen": fact.last_seen,
        }

    await _update_data(db_path, _save)


async def get_setting(key: str, default: str = "", db_path: Path | str = DEFAULT_DB_PATH) -> str:
    """Retrieve a configuration value."""
    data = await _read_data(db_path)
    return str(data.get("settings", {}).get(key, default))


async def set_setting(key: str, value: str, db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Save or update a configuration value."""
    def _set(data: Dict[str, Any]):
        data.setdefault("settings", {})[key] = str(value)

    await _update_data(db_path, _set)


async def get_all_settings(db_path: Path | str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Retrieve all configuration values as typed dict."""
    data = await _read_data(db_path)
    raw = data.get("settings", {})

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
    def _adjust(data: Dict[str, Any]) -> int:
        settings = data.setdefault("settings", {})
        val = str(settings.get("bank_balance", "0"))
        current = int(val) if val.lstrip("-").isdigit() else 0
        new_balance = max(0, current + minutes)
        settings["bank_balance"] = str(new_balance)

        if minutes > 0:
            lt_val = str(settings.get("bank_lifetime", "0"))
            lifetime = int(lt_val) if lt_val.lstrip("-").isdigit() else 0
            settings["bank_lifetime"] = str(lifetime + minutes)

        return new_balance

    return await _update_data(db_path, _adjust)


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

    def _record(data: Dict[str, Any]) -> int:
        events = data.setdefault("reward_events", [])
        next_id = max([e.get("id", 0) for e in events], default=0) + 1
        event = {
            "id": next_id,
            "timestamp": now_iso,
            "minutes_awarded": minutes,
            "questions_answered": questions,
            "synced_to_switch": 1 if synced else 0,
            "device_id": device_id,
            "note": note,
        }
        events.append(event)
        return next_id

    return await _update_data(db_path, _record)


async def get_today_rewarded_minutes(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Calculate the total reward minutes claimed today (UTC)."""
    today_start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    data = await _read_data(db_path)
    total = 0
    for e in data.get("reward_events", []):
        if str(e.get("timestamp", "")).startswith(today_start) and e.get("synced_to_switch") == 1:
            total += int(e.get("minutes_awarded", 0))
    return total


async def get_recent_rewards(limit: int = 10, db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve recent reward history."""
    data = await _read_data(db_path)
    events = list(data.get("reward_events", []))
    events.sort(key=lambda x: x.get("id", 0), reverse=True)
    return events[:limit]


async def reset_today_rewards(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Clear reward events recorded today so the daily reward cap is refreshed."""
    today_start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _reset(data: Dict[str, Any]) -> int:
        events = data.get("reward_events", [])
        remaining = [e for e in events if not str(e.get("timestamp", "")).startswith(today_start)]
        deleted_count = len(events) - len(remaining)
        data["reward_events"] = remaining
        return deleted_count

    return await _update_data(db_path, _reset)


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
