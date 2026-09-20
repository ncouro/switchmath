"""Unit tests for Nintendo Parental Controls integration and conflict resilience."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
import pytest

from app.nintendo.service import NintendoService, _is_bedtime_now
from pynintendoauth.exceptions import HttpException


def test_is_bedtime_now_false_during_day():
    device = MagicMock()
    device.bedtime_alarm = datetime.time(18, 30)
    device.alarms_enabled = True
    device._api._tz = "Europe/London"

    # 16:00 is daytime
    now = datetime.datetime(2026, 9, 14, 16, 0, tzinfo=ZoneInfo("Europe/London"))
    assert _is_bedtime_now(device, now=now) is False


def test_is_bedtime_now_true_at_bedtime():
    device = MagicMock()
    device.bedtime_alarm = datetime.time(18, 30)
    device.alarms_enabled = True
    device._api._tz = "Europe/London"

    # 18:28 (within 5 mins of 18:30)
    now_near = datetime.datetime(2026, 9, 14, 18, 28, tzinfo=ZoneInfo("Europe/London"))
    assert _is_bedtime_now(device, now=now_near) is True

    # 19:15 (past 18:30 bedtime)
    now_past = datetime.datetime(2026, 9, 14, 19, 15, tzinfo=ZoneInfo("Europe/London"))
    assert _is_bedtime_now(device, now=now_past) is True


@pytest.mark.asyncio
async def test_send_extra_time_chunk_fallback_on_409():
    service = NintendoService.__new__(NintendoService)
    
    device = MagicMock()
    device.name = "Switch #1"
    device.device_id = "test_dev_id"
    device.bedtime_alarm = datetime.time(18, 30)
    device.alarms_enabled = True
    device._api._tz = "Europe/London"
    device.update = AsyncMock()

    # Daytime (16:00): prefer_bedtime is False
    # Attempt 1: confirm_no_bedtime raises 409 Conflict
    # Attempt 2: update_extra succeeds
    device._api.async_confirm_extra_playing_time = AsyncMock(side_effect=HttpException(409, "conflict", "conflict"))
    device._api.async_update_extra_playing_time = AsyncMock(return_value={"status": 200, "json": {"status": "TO_ADDED"}})

    with patch("app.nintendo.service._is_bedtime_now", return_value=False):
        await service._send_extra_time_chunk(device, 10)

    # First attempt was called
    device._api.async_confirm_extra_playing_time.assert_called_once_with("test_dev_id", 10, False)
    # Fallback to update_extra was called and succeeded
    device._api.async_update_extra_playing_time.assert_called_once_with("test_dev_id", additional_time=10)


@pytest.mark.asyncio
async def test_cancel_extra_time_skips_when_already_zero():
    service = NintendoService.__new__(NintendoService)
    service._is_connected = True
    service._session_token = "dummy"
    service._lock = MagicMock()
    service._lock.__aenter__ = AsyncMock()
    service._lock.__aexit__ = AsyncMock()

    device = MagicMock()
    device.name = "Switch #1"
    device.device_id = "test_dev_id"
    device.extra_playing_time = None
    device.today_time_remaining = 15
    device.update = AsyncMock()
    device._api = MagicMock()
    device._api.send_request = AsyncMock()

    service._control = MagicMock()
    service._control.devices = {"test_dev_id": device}

    res = await service.cancel_extra_time("test_dev_id")
    assert res["success"] is True
    assert res["extra_playing_time"] == 0
    # No API send_request should be triggered since extra is already 0
    device._api.send_request.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_extra_time_handles_409_conflict():
    service = NintendoService.__new__(NintendoService)
    service._is_connected = True
    service._session_token = "dummy"
    service._lock = MagicMock()
    service._lock.__aenter__ = AsyncMock()
    service._lock.__aexit__ = AsyncMock()

    device = MagicMock()
    device.name = "Switch #1"
    device.device_id = "test_dev_id"
    device.extra_playing_time = 10
    device.today_time_remaining = 25
    device.update = AsyncMock()
    device._api = MagicMock()
    # Nintendo returns 409 Conflict when already canceled on server
    device._api.send_request = AsyncMock(side_effect=HttpException(409, "conflict", "conflict"))

    service._control = MagicMock()
    service._control.devices = {"test_dev_id": device}

    res = await service.cancel_extra_time("test_dev_id")
    assert res["success"] is True
    device._api.send_request.assert_called_once_with(
        endpoint="update_extra_playing_time",
        body={"deviceId": "test_dev_id", "status": "TO_CANCELED"},
    )
