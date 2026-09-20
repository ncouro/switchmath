#!/usr/bin/env python3
"""Nintendo Switch Parental Controls Integration Test CLI.

This script verifies connection to Nintendo Parental Controls using
pantherale0/pynintendoparental. It provides interactive OAuth login
or reuses an existing session token saved in .env, with full debug logging.
"""

import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# Try importing pynintendoparental modules
try:
    from pynintendoauth.exceptions import InvalidSessionTokenException
    from pynintendoparental import Authenticator, NintendoParental
    from pynintendoparental.exceptions import ExtraPlayingTimeActiveError
except ImportError as err:
    print(f"Error: Required package not found ({err}).")
    print("Please activate your virtual environment or run: pip install -r requirements.txt")
    sys.exit(1)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "nintendo_cli_debug.log"


def setup_cli_logging():
    is_debug = "--debug" in sys.argv or "-v" in sys.argv
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG if is_debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        ],
    )
    if is_debug:
        print(f"[DEBUG MODE ENABLED] Logging detailed output to console and {LOG_FILE}")


def save_session_token_to_env(token: str) -> None:
    """Save or update SESSION_TOKEN in the local .env file."""
    lines = []
    found = False
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith("SESSION_TOKEN="):
                lines[i] = f"SESSION_TOKEN={token}\n"
                found = True
                break
    if not found:
        lines.append(f"\nSESSION_TOKEN={token}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"[INFO] Saved SESSION_TOKEN to {ENV_PATH}")


async def interactive_login(session: aiohttp.ClientSession) -> Authenticator:
    """Perform interactive login via browser."""
    auth = Authenticator(client_session=session)
    print("\n" + "=" * 70)
    print("NINTENDO SWITCH PARENTAL CONTROLS - LOGIN SETUP")
    print("=" * 70)
    print("\n1. Open the following URL in your web browser:")
    print(f"\n   {auth.login_url}\n")
    print("2. Log in with the Nintendo Account that manages your Nintendo Switch.")
    print("3. When you see the button labeled 'Select this person' (or 'Use this account'):")
    print("   - Right-click the button (or long-press on mobile/tablet)")
    print("   - Select 'Copy link address' (or 'Copy URL')")
    print("   (The copied URL starts with 'npf...://')\n")

    while True:
        try:
            response_url = input("Paste the copied URL here (or 'q' to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted by user.")
            sys.exit(0)

        if response_url.lower() == "q":
            sys.exit(0)
        if not response_url:
            print("URL cannot be empty. Please paste the redirected URL.")
            continue

        try:
            print("\nCompleting login with Nintendo servers...")
            await auth.async_complete_login(response_url)
            print(">> Login successful!")
            if auth.session_token:
                save_session_token_to_env(auth.session_token)
            return auth
        except Exception as err:
            print(f"[ERROR] Login failed: {err}")
            logging.exception("Interactive login failed")
            print("Please try copying and pasting the URL again.\n")


async def authenticate(session: aiohttp.ClientSession) -> Authenticator:
    """Authenticate using stored session token or interactive browser flow."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    session_token = os.environ.get("SESSION_TOKEN", "").strip()

    if session_token:
        print(f"[INFO] Found SESSION_TOKEN in environment ({session_token[:6]}...{session_token[-4:]})")
        choice = input("Use existing session token? [Y/n]: ").strip().lower()
        if choice in ("", "y", "yes"):
            try:
                auth = Authenticator(session_token=session_token, client_session=session)
                await auth.async_complete_login(use_session_token=True)
                print(">> Authenticated successfully with existing session token!")
                return auth
            except InvalidSessionTokenException:
                print("[WARNING] The stored session token is expired or invalid.")
            except Exception as err:
                print(f"[WARNING] Session login failed ({err}). Falling back to interactive login.")
                logging.exception("Token authentication failed")

    return await interactive_login(session)


async def main():
    setup_cli_logging()
    print("Initializing Nintendo Switch Parental Controls test...")
    async with aiohttp.ClientSession() as session:
        auth = await authenticate(session)

        print("\nFetching connected Nintendo Switch consoles...")
        try:
            control = await NintendoParental.create(auth)
        except Exception as err:
            print(f"[ERROR] Failed to fetch Parental Controls data: {err}")
            logging.exception("Failed to fetch parental controls data")
            sys.exit(1)

        devices = list(control.devices.values())
        if not devices:
            print("\n[!] No Nintendo Switch devices found in this Parental Controls account.")
            print("Make sure your Switch is linked to the Nintendo Switch Parental Controls mobile app.")
            return

        print(f"\nFound {len(devices)} device(s):")
        print("-" * 70)
        for i, device in enumerate(devices, 1):
            limit_str = (
                f"{device.limit_time} mins"
                if device.limit_time not in (None, -1)
                else "No limit / Not set"
            )
            extra_str = f"{device.extra_playing_time} mins" if device.extra_playing_time else "0 mins"
            rem_str = (
                f"{device.today_time_remaining} mins"
                if device.today_time_remaining is not None
                else "Unknown"
            )
            bedtime_str = f"{device.bedtime_alarm}" if getattr(device, "bedtime_alarm", None) else "Not set"

            print(f"[{i}] {device.name} (ID: {device.device_id})")
            print(f"    - Daily Playtime Limit:  {limit_str}")
            print(f"    - Time Played Today:     {device.today_playing_time} mins")
            print(f"    - Time Remaining Today:  {rem_str}")
            print(f"    - Extra Time Added Today:{extra_str}")
            print(f"    - Bedtime Alarm:         {bedtime_str}")
            print(f"    - Sync State / Updated:  {getattr(device, 'sync_state', 'N/A')}")
            print("-" * 70)

        # Interactive verification: Test adding time
        selected_device = devices[0]
        if len(devices) > 1:
            try:
                choice = input(f"Select a device [1-{len(devices)}] to test (default 1): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(devices):
                    selected_device = devices[int(choice) - 1]
            except (EOFError, KeyboardInterrupt):
                return

        print(f"\nTarget console: {selected_device.name} ({selected_device.device_id})")
        print("\nWould you like to test adding extra playing time to this console?")
        print("This will send a live request to Nintendo's API.")
        try:
            test_add = input("Add test extra time (e.g. +5 mins)? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if test_add in ("y", "yes"):
            try:
                mins_input = input("Minutes to add (default 5): ").strip()
                mins = int(mins_input) if mins_input.isdigit() else 5
                print(f"Sending request: +{mins} minutes to {selected_device.name}...")
                await selected_device.add_extra_time(mins)
                print(f">> SUCCESS! Added {mins} minutes extra playtime.")
                print(f"   Current extra playing time: {selected_device.extra_playing_time} mins")
                print(f"   Remaining playtime today:   {selected_device.today_time_remaining} mins")

                # Check bedtime warning
                if getattr(selected_device, "bedtime_alarm", None):
                    print(f"\n[NOTE] Bedtime alarm is set to {selected_device.bedtime_alarm}.")
                    print("If current time is past bedtime, the Switch will remain locked until bedtime is extended.")

                # Option to cancel
                cancel_test = input("\nWould you like to cancel / revoke this extra time now? [y/N]: ").strip().lower()
                if cancel_test in ("y", "yes"):
                    print("Revoking extra playing time...")
                    await selected_device.cancel_extra_time()
                    print(">> SUCCESS! Extra playing time reverted.")
            except ExtraPlayingTimeActiveError as err:
                print(f"[ERROR] Nintendo extra playing time already active: {err}")
                logging.exception("Extra playing time error")
            except Exception as err:
                print(f"[ERROR] Unexpected error during extra time update: {err}")
                logging.exception("Unexpected error")
                traceback.print_exc()

        print("\nTest completed successfully!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
