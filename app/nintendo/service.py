"""Nintendo Parental Controls Integration Service.

Manages connection to Nintendo Parental Controls via pynintendoparental,
handles authentication, device state, diagnostics, and granting playtime rewards.
"""

from __future__ import annotations

import asyncio
import datetime
from zoneinfo import ZoneInfo
import logging
import os
import traceback
from typing import Any, Dict, List, Optional

import aiohttp
import json
from dotenv import load_dotenv

logger = logging.getLogger("app.nintendo")
nintendo_api_logger = logging.getLogger("nintendo.api")

try:
    from pynintendoauth.exceptions import InvalidSessionTokenException
    from pynintendoparental import Authenticator, NintendoParental
    from pynintendoparental.api import Api, ENDPOINTS, BASE_URL
    from pynintendoparental.device._helpers import is_bedtime_disabled
    from pynintendoparental.exceptions import ExtraPlayingTimeActiveError
    NINTENDO_AVAILABLE = True

    _orig_send_request = Api.send_request

    async def _logging_send_request(self, endpoint: str, body: object = None, **kwargs):
        e_point = ENDPOINTS.get(endpoint, {})
        url = e_point.get("url", "").format(BASE_URL=BASE_URL, **kwargs)
        method = e_point.get("method", "POST" if body is not None else "GET")

        body_str = json.dumps(body) if isinstance(body, (dict, list)) else (str(body) if body is not None else "none")
        nintendo_api_logger.info(
            ">> Nintendo API Request: %s %s | endpoint=%s | body=%s",
            method,
            url,
            endpoint,
            body_str,
        )

        try:
            resp = await _orig_send_request(self, endpoint, body=body, **kwargs)
            status = resp.get("status")
            raw_payload = resp.get("json") or resp.get("text", "")
            if isinstance(raw_payload, (dict, list)):
                payload_str = json.dumps(raw_payload)
            else:
                payload_str = str(raw_payload)

            if len(payload_str) > 250:
                payload_str = payload_str[:250] + "... (truncated)"

            nintendo_api_logger.info(
                "<< Nintendo API Response: %s %s -> status=%s | payload=%s",
                method,
                endpoint,
                status,
                payload_str,
            )
            return resp
        except Exception as err:
            nintendo_api_logger.error(
                "<< Nintendo API Error: %s %s | endpoint=%s | error=%s",
                method,
                url,
                endpoint,
                err,
            )
            raise

    Api.send_request = _logging_send_request

    # Fix typo in pynintendoparental: Nintendo's Enum strictly requires 'TO_CANCELED' (single L)
    async def _patched_update_extra_playing_time(self, device_id: str, additional_time: int | None = None, cancel: bool = False) -> dict:
        body: dict = {"deviceId": device_id}
        if cancel:
            body["status"] = "TO_CANCELED"
        elif additional_time == -1 and not cancel:
            body["status"] = "TO_INFINITY"
        elif additional_time is not None:
            body["additionalTime"] = additional_time
            body["status"] = "TO_ADDED"
        else:
            raise ValueError("Additional time must be provided if not canceling")
        return await self.send_request(endpoint="update_extra_playing_time", body=body)

    Api.async_update_extra_playing_time = _patched_update_extra_playing_time

except ImportError:
    logger.warning("pynintendoparental or pynintendoauth is not available.")
    NINTENDO_AVAILABLE = False


def _is_bedtime_now(device: Any, now: Optional[datetime.datetime] = None) -> bool:
    """Check if current local time is close to or past bedtime alarm for today."""
    if not getattr(device, "bedtime_alarm", None) or is_bedtime_disabled(device.bedtime_alarm):
        return False
    if not getattr(device, "alarms_enabled", True):
        return False
    if now is None:
        raw_tz = getattr(device._api, "_tz", None)
        tz = ZoneInfo(raw_tz) if isinstance(raw_tz, str) else (raw_tz or datetime.timezone.utc)
        now = datetime.datetime.now(tz)
    current_minutes = now.hour * 60 + now.minute
    bedtime = device.bedtime_alarm
    bedtime_minutes = bedtime.hour * 60 + bedtime.minute
    return current_minutes >= (bedtime_minutes - 5)


class NintendoService:
    """Service wrapping Nintendo Parental Controls functionality."""

    def __init__(self, session_token: Optional[str] = None):
        self._session_token: Optional[str] = session_token
        self._authenticator: Optional[Any] = None
        self._control: Optional[Any] = None
        self._client_session: Optional[aiohttp.ClientSession] = None
        self._is_connected: bool = False
        self._lock = asyncio.Lock()
        self._last_error: Optional[str] = None

        if not self._session_token:
            self.reload_token_from_env()

    def reload_token_from_env(self) -> Optional[str]:
        """Reload SESSION_TOKEN from .env file."""
        load_dotenv(override=True)
        token = os.environ.get("SESSION_TOKEN", "").strip()
        if token:
            self._session_token = token
            logger.debug("Loaded session token from .env (%s...%s)", token[:6], token[-4:])
        return self._session_token

    async def _get_client_session(self) -> aiohttp.ClientSession:
        if self._client_session is None or self._client_session.closed:
            self._client_session = aiohttp.ClientSession()
        return self._client_session

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._control is not None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    async def connect_with_token(self, session_token: Optional[str] = None) -> bool:
        """Connect to Nintendo using a saved session token."""
        if not NINTENDO_AVAILABLE:
            self._last_error = "pynintendoparental library is not installed."
            logger.error(self._last_error)
            return False

        token = session_token or self._session_token or self.reload_token_from_env()
        if not token:
            self._last_error = "No SESSION_TOKEN found in environment or settings."
            logger.info(self._last_error)
            return False

        async with self._lock:
            try:
                logger.info("Connecting to Nintendo Parental Controls with session token...")
                session = await self._get_client_session()
                auth = Authenticator(session_token=token, client_session=session)
                await auth.async_complete_login(use_session_token=True)
                self._authenticator = auth
                self._session_token = token
                self._control = await NintendoParental.create(auth)
                self._is_connected = True
                self._last_error = None

                device_count = len(self._control.devices)
                logger.info("Connected to Nintendo Parental Controls successfully! Found %d device(s).", device_count)
                for d in self._control.devices.values():
                    logger.info(" - Switch: '%s' (ID: %s, Limit: %s min, Extra: %s min, Remaining: %s min)",
                                d.name, d.device_id, d.limit_time, d.extra_playing_time, d.today_time_remaining)
                return True
            except Exception as err:
                self._last_error = f"Authentication error: {err}"
                logger.exception("Failed to connect to Nintendo with session token: %s", err)
                self._is_connected = False
                return False

    async def start_interactive_login(self) -> str:
        """Create a new Authenticator and return the login URL for the user."""
        if not NINTENDO_AVAILABLE:
            raise RuntimeError("pynintendoparental is not available.")

        session = await self._get_client_session()
        self._authenticator = Authenticator(client_session=session)
        logger.info("Generated new Nintendo OAuth login URL: %s", self._authenticator.login_url)
        return self._authenticator.login_url

    async def complete_interactive_login(self, response_url: str) -> str:
        """Complete the interactive login using the callback URL."""
        if not self._authenticator:
            raise RuntimeError("Interactive login was not started. Please request a login URL first.")

        logger.info("Completing interactive login with response URL...")
        await self._authenticator.async_complete_login(response_url)
        token = self._authenticator.session_token
        self._session_token = token

        # Connect NintendoParental
        self._control = await NintendoParental.create(self._authenticator)
        self._is_connected = True
        self._last_error = None
        logger.info("Interactive login completed successfully. Session token acquired.")
        return token

    async def get_devices(self) -> List[Dict[str, Any]]:
        """Return a list of all Nintendo Switch consoles and their detailed stats."""
        if not self.is_connected:
            # Try auto-connecting if token exists
            if self._session_token or self.reload_token_from_env():
                await self.connect_with_token()

        if not self.is_connected:
            return []

        async with self._lock:
            try:
                await self._control.update()
            except Exception as err:
                logger.warning("Failed to refresh Nintendo devices: %s", err)

            device_list = []
            for d in self._control.devices.values():
                bedtime_str = str(d.bedtime_alarm) if getattr(d, "bedtime_alarm", None) else None
                device_list.append({
                    "device_id": d.device_id,
                    "name": d.name,
                    "limit_time": d.limit_time,
                    "today_playing_time": d.today_playing_time,
                    "today_time_remaining": d.today_time_remaining,
                    "extra_playing_time": d.extra_playing_time or 0,
                    "bedtime_alarm": bedtime_str,
                    "alarms_enabled": getattr(d, "alarms_enabled", True),
                    "sync_state": getattr(d, "sync_state", None),
                })
            return device_list

    async def _send_extra_time_chunk(self, device: Any, chunk: int) -> None:
        """Send a single chunk of extra playing time (<= 60 mins) with automatic fallback.

        Nintendo requires withBedtime=false for standard daytime playtime extensions.
        If bedtime is currently active, withBedtime=true is tried first.
        If any attempt raises HTTP 409 (conflict) or other errors, it automatically falls
        back to alternative endpoints / parameters.
        """
        prefer_bedtime = _is_bedtime_now(device)
        logger.debug("Granting extra time chunk %dm to '%s' (prefer_bedtime=%s)", chunk, device.name, prefer_bedtime)

        attempts = []
        if prefer_bedtime:
            attempts.append(("confirm_with_bedtime", lambda: device._api.async_confirm_extra_playing_time(device.device_id, chunk, True)))
            attempts.append(("confirm_no_bedtime", lambda: device._api.async_confirm_extra_playing_time(device.device_id, chunk, False)))
            attempts.append(("update_extra", lambda: device._api.async_update_extra_playing_time(device.device_id, additional_time=chunk)))
        else:
            attempts.append(("confirm_no_bedtime", lambda: device._api.async_confirm_extra_playing_time(device.device_id, chunk, False)))
            attempts.append(("update_extra", lambda: device._api.async_update_extra_playing_time(device.device_id, additional_time=chunk)))
            attempts.append(("confirm_with_bedtime", lambda: device._api.async_confirm_extra_playing_time(device.device_id, chunk, True)))

        last_err = None
        for name, func in attempts:
            try:
                res = await func()
                logger.info(
                    "Successfully granted %dm extra time via %s to '%s': %s",
                    chunk,
                    name,
                    device.name,
                    res.get("json") if isinstance(res, dict) else res,
                )
                return
            except Exception as err:
                last_err = err
                logger.warning("Extra time grant attempt '%s' for '%s' failed: %s. Trying fallback...", name, device.name, err)
                await asyncio.sleep(0.5)
                try:
                    await device.update()
                except Exception:
                    pass

        if last_err:
            raise last_err

    async def add_extra_time(self, device_id: Optional[str], minutes: int) -> Dict[str, Any]:
        """Add extra playtime minutes to the specified Nintendo Switch."""
        if not self.is_connected:
            if self._session_token or self.reload_token_from_env():
                await self.connect_with_token()

        if not self.is_connected:
            msg = self._last_error or "Nintendo Parental Controls is not connected."
            logger.error("add_extra_time called but Nintendo is not connected: %s", msg)
            return {"success": False, "message": msg}

        async with self._lock:
            devices = self._control.devices
            device = None
            if device_id and device_id in devices:
                device = devices[device_id]
            elif devices:
                device = list(devices.values())[0]

            if not device:
                msg = "No Nintendo Switch console found on this Parental Controls account."
                logger.error(msg)
                return {"success": False, "message": msg}

            # Refresh device state before computing overtime deficit and adding time
            try:
                await device.update()
            except Exception as err:
                logger.warning("Failed to refresh device before adding extra time: %s", err)

            before_extra = device.extra_playing_time or 0
            before_remaining = device.today_time_remaining or 0
            limit_time = device.limit_time or 0
            played_time = device.today_playing_time or 0

            # If the console is currently expired/locked (remaining <= 0 and played >= limit),
            # the extra time granted must cover the existing overtime deficit so that the console
            # actually unlocks with `minutes` of playable screen time.
            if before_remaining <= 0 and played_time >= limit_time and before_extra == 0:
                deficit = played_time - limit_time
                minutes_to_add = deficit + minutes
                logger.info(
                    "Console '%s' is in overtime (%dm played vs %dm limit). "
                    "Granting deficit (%dm) + bonus (%dm) = %dm extra time to unlock.",
                    device.name, played_time, limit_time, deficit, minutes, minutes_to_add
                )
            else:
                minutes_to_add = minutes

            logger.info(">> Nintendo API Request: Adding +%d mins to '%s' (current extra: %d min, remaining: %s min)",
                        minutes_to_add, device.name, before_extra, before_remaining)

            try:
                # Nintendo Parental API caps single extra time additions to 60 minutes
                # Chunk into increments <= 60
                remaining_to_add = minutes_to_add
                while remaining_to_add > 0:
                    chunk = min(60, remaining_to_add)
                    await self._send_extra_time_chunk(device, chunk)
                    remaining_to_add -= chunk
                    if remaining_to_add > 0:
                        await asyncio.sleep(1.0)

                # Wait 1.0s for Nintendo background workers to process, then refresh
                await asyncio.sleep(1.0)
                await device.update()

                after_extra = device.extra_playing_time or 0
                after_remaining = device.today_time_remaining
                logger.info("Nintendo playtime updated! '%s' extra is now %s min, remaining is %s min",
                            device.name, after_extra, after_remaining)
                return {
                    "success": True,
                    "device_name": device.name,
                    "device_id": device.device_id,
                    "minutes_added": minutes,
                    "effective_extra_granted": minutes_to_add,
                    "previous_extra": before_extra,
                    "extra_playing_time": after_extra,
                    "today_time_remaining": after_remaining,
                    "message": f"Successfully added +{minutes} minutes to {device.name}!",
                }
            except Exception as err:
                logger.exception("Nintendo rejected extra time update: %s", err)
                return {
                    "success": False,
                    "message": f"Nintendo error: {err}",
                    "traceback": traceback.format_exc(),
                }

    async def cancel_extra_time(self, device_id: Optional[str]) -> Dict[str, Any]:
        """Cancel/reset any extra playing time active on the console for today."""
        if not self.is_connected:
            if self._session_token or self.reload_token_from_env():
                await self.connect_with_token()

        if not self.is_connected:
            return {"success": False, "message": "Nintendo is not connected."}

        async with self._lock:
            devices = self._control.devices
            device = devices.get(device_id) if device_id else (list(devices.values())[0] if devices else None)
            if not device:
                return {"success": False, "message": "No console found."}

            try:
                # Refresh device state first
                try:
                    await device.update()
                except Exception as err:
                    logger.warning("Failed to refresh device before cancelling extra time: %s", err)

                current_extra = device.extra_playing_time or 0
                if current_extra <= 0:
                    logger.info("Console '%s' has no extra time active (already 0).", device.name)
                    return {
                        "success": True,
                        "device_name": device.name,
                        "extra_playing_time": 0,
                        "today_time_remaining": device.today_time_remaining,
                        "message": f"Extra time on {device.name} is already 0.",
                    }

                body = {"deviceId": device.device_id, "status": "TO_CANCELED"}
                try:
                    await device._api.send_request(endpoint="update_extra_playing_time", body=body)
                except Exception as err:
                    if "409" in str(err) or "conflict" in str(err).lower():
                        logger.warning("Cancel returned 409 Conflict (already cancelled on server): %s", err)
                    else:
                        raise

                device.extra_playing_time = None
                await asyncio.sleep(1.0)
                await device.update()
                return {
                    "success": True,
                    "device_name": device.name,
                    "extra_playing_time": device.extra_playing_time or 0,
                    "today_time_remaining": device.today_time_remaining,
                    "message": f"Extra time on {device.name} has been reset to 0.",
                }
            except Exception as err:
                logger.exception("Nintendo failed to cancel extra time: %s", err)
                return {"success": False, "message": str(err)}

    async def diagnose_connection(self) -> Dict[str, Any]:
        """Run a full connection diagnostic check and return structured report."""
        report: Dict[str, Any] = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "has_session_token": False,
            "token_preview": None,
            "auth_status": "NOT_STARTED",
            "devices": [],
            "error": None,
            "steps": [],
        }

        token = self._session_token or self.reload_token_from_env()
        if not token:
            report["error"] = "No SESSION_TOKEN found in .env or settings."
            report["steps"].append("Check: No token found. Please connect your Nintendo account.")
            return report

        report["has_session_token"] = True
        report["token_preview"] = f"{token[:8]}...{token[-6:]}"
        report["steps"].append(f"Found token: {report['token_preview']}")

        try:
            session = await self._get_client_session()
            auth = Authenticator(session_token=token, client_session=session)
            report["steps"].append("Authenticating session token with accounts.nintendo.com...")
            await auth.async_complete_login(use_session_token=True)
            report["steps"].append("Authentication completed. Token is VALID.")

            report["steps"].append("Connecting to Nintendo Parental Controls API...")
            control = await NintendoParental.create(auth)
            report["steps"].append("Parental Controls data retrieved.")

            self._authenticator = auth
            self._control = control
            self._is_connected = True
            report["auth_status"] = "CONNECTED"

            for d in control.devices.values():
                d_info = {
                    "device_id": d.device_id,
                    "name": d.name,
                    "limit_time": d.limit_time,
                    "today_playing_time": d.today_playing_time,
                    "today_time_remaining": d.today_time_remaining,
                    "extra_playing_time": d.extra_playing_time or 0,
                    "bedtime_alarm": str(d.bedtime_alarm) if getattr(d, "bedtime_alarm", None) else None,
                    "alarms_enabled": getattr(d, "alarms_enabled", None),
                }
                report["devices"].append(d_info)
                report["steps"].append(
                    f"Console found: {d.name} (Playtime limit: {d.limit_time}m, Extra: {d.extra_playing_time}m, Remaining: {d.today_time_remaining}m)"
                )

            return report

        except Exception as err:
            report["auth_status"] = "FAILED"
            report["error"] = str(err)
            report["steps"].append(f"ERROR: {err}")
            logger.exception("Diagnostic connection check failed: %s", err)
            return report

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._client_session and not self._client_session.closed:
            await self._client_session.close()
