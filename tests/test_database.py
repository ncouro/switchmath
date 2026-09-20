"""Unit tests for the database persistence module."""

import os
from pathlib import Path
import pytest

from app.db.database import (
    init_db,
    load_facts,
    save_fact,
    get_setting,
    set_setting,
    get_all_settings,
    record_reward_event,
    get_today_rewarded_minutes,
    get_recent_rewards,
    reset_today_rewards,
    adjust_bank_minutes,
    get_bank_balance,
    reset_bank_balance,
)
from app.learning.engine import FactRecord


@pytest.fixture
async def temp_db(tmp_path):
    db_file = tmp_path / "test_rewards.db"
    await init_db(db_file)
    return db_file


@pytest.mark.asyncio
async def test_init_and_default_settings(temp_db):
    settings = await get_all_settings(temp_db)
    assert settings["questions_per_reward"] == 15
    assert settings["minutes_per_reward"] == 5
    assert settings["max_daily_reward_minutes"] == 60
    assert settings["speed_threshold_ms"] == 4000.0


@pytest.mark.asyncio
async def test_fact_save_and_load(temp_db):
    fact = FactRecord(
        factor_a=7,
        factor_b=8,
        box=3,
        consecutive_correct=4,
        attempts=5,
        wrong_count=1,
        last_latency_ms=2100.0,
        avg_latency_ms=2500.0,
    )
    await save_fact(fact, temp_db)

    loaded = await load_facts(temp_db)
    assert "7x8" in loaded
    f = loaded["7x8"]
    assert f.factor_a == 7
    assert f.factor_b == 8
    assert f.box == 3
    assert f.consecutive_correct == 4
    assert f.attempts == 5
    assert f.wrong_count == 1
    assert f.avg_latency_ms == 2500.0


@pytest.mark.asyncio
async def test_reward_events_and_daily_calculation(temp_db):
    # Record two rewards
    id1 = await record_reward_event(
        minutes=5,
        questions=10,
        synced=True,
        device_id="switch-1",
        note="Earned 5m",
        db_path=temp_db,
    )
    assert id1 > 0

    id2 = await record_reward_event(
        minutes=10,
        questions=20,
        synced=True,
        device_id="switch-1",
        note="Earned 10m",
        db_path=temp_db,
    )
    assert id2 > 0

    # Unsynced reward should not count toward today's synced minutes
    await record_reward_event(
        minutes=15,
        questions=30,
        synced=False,
        device_id="switch-1",
        note="Pending",
        db_path=temp_db,
    )

    today_total = await get_today_rewarded_minutes(temp_db)
    assert today_total == 15

    recent = await get_recent_rewards(limit=5, db_path=temp_db)
    assert len(recent) == 3
    assert recent[0]["minutes_awarded"] == 15


@pytest.mark.asyncio
async def test_reset_today_rewards(temp_db):
    await record_reward_event(
        minutes=10,
        questions=20,
        synced=True,
        device_id="switch-1",
        note="Earned 10m",
        db_path=temp_db,
    )
    today_total = await get_today_rewarded_minutes(temp_db)
    assert today_total == 10

    deleted = await reset_today_rewards(temp_db)
    assert deleted >= 1

    today_total_after = await get_today_rewarded_minutes(temp_db)
    assert today_total_after == 0


@pytest.mark.asyncio
async def test_reset_bank_balance(temp_db):
    await adjust_bank_minutes(25, "Earned bonus", temp_db)
    balance = await get_bank_balance(temp_db)
    assert balance == 25

    res = await reset_bank_balance(temp_db)
    assert res == 0
    balance_after = await get_bank_balance(temp_db)
    assert balance_after == 0

