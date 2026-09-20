"""FastAPI Web Application for Times Tables & Nintendo Switch Rewards."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db.database import (
    DEFAULT_DB_PATH,
    adjust_bank_minutes,
    get_all_settings,
    get_bank_balance,
    get_recent_rewards,
    get_today_rewarded_minutes,
    init_db,
    load_facts,
    record_reward_event,
    reset_bank_balance,
    reset_today_rewards,
    save_fact,
    set_setting,
)
from app.learning.engine import RepetitionEngine
from app.logging_config import clear_logs, get_recent_logs, setup_logging
from app.nintendo.service import NintendoService

setup_logging()
logger = logging.getLogger("app.main")

# State container
class AppState:
    engine: RepetitionEngine
    nintendo: NintendoService
    selected_device_id: Optional[str] = None
    session_correct_count: int = 0
    session_total_count: int = 0
    unclaimed_correct_count: int = 0

state = AppState()
STATIC_DIR = Path(__file__).resolve().parent / "static"


def get_db_path() -> str:
    """Return configured database path or default JSON store."""
    return os.environ.get("DATABASE_PATH", str(DEFAULT_DB_PATH))



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan setup: DB init, load stats, connect Nintendo."""
    load_dotenv(override=True)
    db_path = get_db_path()
    await init_db(db_path)

    settings = await get_all_settings(db_path)
    state.engine = RepetitionEngine(
        min_table=2,
        max_table=12,
        speed_threshold_ms=settings["speed_threshold_ms"],
        retry_delay_questions=settings["retry_delay_questions"],
        active_tables=settings["active_tables"],
        exclude_tens=settings.get("exclude_tens", False),
        exclude_elevens_single_digit=settings.get("exclude_elevens_single_digit", settings.get("exclude_elevens_two_digit", False)),
        exclude_twos=settings.get("exclude_twos", False),
    )

    # Load persisted facts into engine
    persisted_facts = await load_facts(db_path)
    for key, fact in persisted_facts.items():
        state.engine.facts[key] = fact

    # Initialize Nintendo Service
    session_token = os.environ.get("SESSION_TOKEN")
    state.nintendo = NintendoService(session_token=session_token)
    state.selected_device_id = os.environ.get("SELECTED_DEVICE_ID")

    if session_token:
        connected = await state.nintendo.connect_with_token(session_token)
        if connected:
            logger.info("Auto-connected to Nintendo Parental Controls on startup.")
        else:
            logger.warning("Could not auto-connect to Nintendo: %s", state.nintendo.last_error)

    yield

    await state.nintendo.close()


app = FastAPI(title="Times Tables Nintendo Rewards", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Request Models
class AnswerSubmission(BaseModel):
    factor_a: int = Field(..., ge=2, le=12)
    factor_b: int = Field(..., ge=2, le=12)
    user_answer: int
    latency_ms: float = Field(..., ge=0)


class SettingsUpdate(BaseModel):
    questions_per_reward: Optional[int] = Field(None, ge=1, le=100)
    minutes_per_reward: Optional[int] = Field(None, ge=1, le=120)
    max_daily_reward_minutes: Optional[int] = Field(None, ge=0, le=600)
    speed_threshold_ms: Optional[float] = Field(None, ge=1000, le=20000)
    active_tables: Optional[List[int]] = None
    selected_device_id: Optional[str] = None
    reward_mode: Optional[str] = Field(None, pattern="^(bank|hybrid|nintendo|manual)$")
    exclude_tens: Optional[bool] = None
    exclude_elevens_single_digit: Optional[bool] = None
    exclude_elevens_two_digit: Optional[bool] = None
    exclude_twos: Optional[bool] = None


class BankAdjustment(BaseModel):
    minutes: int = Field(..., ge=-600, le=600)
    reason: Optional[str] = "Manual adjustment"


class ManualTimeInjection(BaseModel):
    device_id: Optional[str] = None
    minutes: int = Field(..., ge=1, le=180)


class LoginCompletion(BaseModel):
    response_url: str


# API Routes

@app.get("/api/status")
async def get_status():
    """Return system, nintendo, and current session status."""
    db_path = get_db_path()
    settings = await get_all_settings(db_path)
    today_rewarded = await get_today_rewarded_minutes(db_path)
    bank_balance = await get_bank_balance(db_path)

    # If Nintendo is disconnected but token exists in env, attempt auto-reconnect
    if not state.nintendo.is_connected and (os.environ.get("SESSION_TOKEN") or state.nintendo.reload_token_from_env()):
        await state.nintendo.connect_with_token()

    devices = await state.nintendo.get_devices() if state.nintendo.is_connected else []

    return {
        "nintendo_connected": state.nintendo.is_connected,
        "nintendo_last_error": state.nintendo.last_error,
        "selected_device_id": state.selected_device_id,
        "devices": devices,
        "session": {
            "total_answered": state.session_total_count,
            "correct_answered": state.session_correct_count,
            "unclaimed_correct": state.unclaimed_correct_count,
            "accuracy_percent": round(
                (state.session_correct_count / max(1, state.session_total_count)) * 100
            ),
        },
        "rewards": {
            "today_rewarded_minutes": today_rewarded,
            "max_daily_minutes": settings["max_daily_reward_minutes"],
            "questions_per_reward": settings["questions_per_reward"],
            "minutes_per_reward": settings["minutes_per_reward"],
            "reward_mode": settings.get("reward_mode", "bank"),
            "bank_balance": bank_balance,
            "bank_lifetime": settings.get("bank_lifetime", 0),
            "progress_to_next_reward": (
                state.unclaimed_correct_count % settings["questions_per_reward"]
            ),
        },
        "active_tables": list(state.engine.active_tables),
        "exclude_twos": state.engine.exclude_twos,
        "exclude_tens": state.engine.exclude_tens,
        "exclude_elevens_single_digit": state.engine.exclude_elevens_single_digit,
        "exclude_elevens_two_digit": state.engine.exclude_elevens_single_digit,
    }


@app.get("/api/quiz/next")
async def get_next_question():
    """Retrieve the next question scheduled by the delayed repetition engine."""
    a, b, reason = state.engine.get_next_question()
    fact_key = f"{a}x{b}"
    fact = state.engine.facts.get(fact_key)

    return {
        "factor_a": a,
        "factor_b": b,
        "prompt_reason": reason,
        "current_box": fact.box if fact else 0,
        "is_retry": reason.startswith("retry_"),
        "active_retry_queue_size": len(state.engine.retry_queue),
    }


@app.post("/api/quiz/answer")
async def submit_answer(payload: AnswerSubmission):
    """Process an answer, update delayed repetition queue, and credit rewards."""
    db_path = get_db_path()
    settings = await get_all_settings(db_path)
    reward_mode = settings.get("reward_mode", "bank")

    # 1. Evaluate with Repetition Engine
    eval_result = state.engine.record_answer(
        factor_a=payload.factor_a,
        factor_b=payload.factor_b,
        user_answer=payload.user_answer,
        latency_ms=payload.latency_ms,
    )

    # 2. Persist fact learning state to JSON storage
    fact = state.engine.facts[f"{payload.factor_a}x{payload.factor_b}"]
    await save_fact(fact, db_path)

    # 3. Update session statistics
    state.session_total_count += 1
    reward_earned = False
    reward_info = None

    if eval_result["is_correct"]:
        state.session_correct_count += 1
        state.unclaimed_correct_count += 1

        # Check if reward milestone reached
        q_threshold = settings["questions_per_reward"]
        if state.unclaimed_correct_count >= q_threshold:
            mins_to_grant = settings["minutes_per_reward"]
            max_daily = settings["max_daily_reward_minutes"]
            today_awarded = await get_today_rewarded_minutes(db_path)

            if max_daily > 0 and (today_awarded + mins_to_grant) > max_daily:
                mins_to_grant = max(0, max_daily - today_awarded)

            if mins_to_grant > 0:
                reward_earned = True
                synced_to_switch = False
                nintendo_msg = f"+{mins_to_grant}m added to your Time Bank!"

                # Always add earned time to the local Time Bank
                new_bank = await adjust_bank_minutes(
                    mins_to_grant, f"Quiz milestone ({q_threshold} correct)", db_path
                )

                # If nintendo or hybrid mode: also attempt Switch sync directly
                if reward_mode in ("hybrid", "nintendo") and state.nintendo.is_connected:
                    add_res = await state.nintendo.add_extra_time(
                        device_id=state.selected_device_id, minutes=mins_to_grant
                    )
                    synced_to_switch = add_res.get("success", False)
                    if synced_to_switch:
                        nintendo_msg = f"Added +{mins_to_grant}m to {add_res.get('device_name', 'Switch')}!"
                    else:
                        nintendo_msg = f"Saved to Bank (Switch sync error: {add_res.get('message')})"

                await record_reward_event(
                    minutes=mins_to_grant,
                    questions=q_threshold,
                    synced=synced_to_switch,
                    device_id=state.selected_device_id,
                    note=nintendo_msg,
                    db_path=db_path,
                )

                state.unclaimed_correct_count -= q_threshold
                reward_info = {
                    "minutes": mins_to_grant,
                    "synced": synced_to_switch,
                    "bank_balance": new_bank,
                    "message": nintendo_msg,
                    "today_total": today_awarded + mins_to_grant,
                }

    bank_balance = await get_bank_balance(db_path)
    return {
        "evaluation": eval_result,
        "reward_earned": reward_earned,
        "reward_info": reward_info,
        "bank_balance": bank_balance,
        "unclaimed_correct": state.unclaimed_correct_count,
        "progress_to_next": state.unclaimed_correct_count % settings["questions_per_reward"],
        "questions_per_reward": settings["questions_per_reward"],
    }


# Manual Time Bank & Direct Switch Injection

@app.post("/api/bank/adjust")
async def adjust_bank(payload: BankAdjustment):
    """Manually add or deduct minutes from the child's screen time bank."""
    db_path = get_db_path()
    new_balance = await adjust_bank_minutes(payload.minutes, payload.reason or "Manual", db_path)

    note = f"Manual Bank {'+' if payload.minutes >= 0 else ''}{payload.minutes}m: {payload.reason}"
    await record_reward_event(
        minutes=payload.minutes,
        questions=0,
        synced=False,
        note=note,
        db_path=db_path,
    )
    logger.info("Bank adjusted by %d mins. New balance: %d. Reason: %s", payload.minutes, new_balance, payload.reason)

    return {
        "success": True,
        "adjusted_minutes": payload.minutes,
        "new_balance": new_balance,
        "message": f"Successfully updated bank balance to {new_balance} minutes.",
    }


@app.post("/api/bank/withdraw")
@app.post("/api/bank/sync-to-switch")
async def sync_bank_to_switch(payload: ManualTimeInjection):
    """Transfer minutes from the Screen Time Bank directly to Nintendo Switch."""
    db_path = get_db_path()
    bank_balance = await get_bank_balance(db_path)

    if payload.minutes > bank_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Requested {payload.minutes}m exceeds current bank balance ({bank_balance}m).",
        )

    if not state.nintendo.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Nintendo Switch is not connected. Connect in Settings or check Diagnostics.",
        )

    res = await state.nintendo.add_extra_time(payload.device_id or state.selected_device_id, payload.minutes)
    if not res.get("success"):
        raise HTTPException(status_code=502, detail=res.get("message", "Nintendo API error"))

    # Deduct transferred minutes from bank
    new_bank = await adjust_bank_minutes(-payload.minutes, "Transferred to Nintendo Switch", db_path)
    await record_reward_event(
        minutes=payload.minutes,
        questions=0,
        synced=True,
        device_id=res.get("device_id"),
        note=f"Bank -> Switch: +{payload.minutes}m to {res.get('device_name')}",
        db_path=db_path,
    )

    return {
        "status": "ok",
        "success": True,
        "minutes_transferred": payload.minutes,
        "new_bank_balance": new_bank,
        "bank_balance": new_bank,
        "device_name": res.get("device_name"),
        "today_time_remaining": res.get("today_time_remaining"),
        "message": f"Successfully sent +{payload.minutes} minutes to {res.get('device_name')}!",
    }


@app.post("/api/bank/reset")
async def reset_bank_endpoint():
    """Reset the screen time bank balance back to 0."""
    db_path = get_db_path()
    await reset_bank_balance(db_path)
    logger.info("Screen Time Bank balance was reset to 0.")
    return {
        "status": "ok",
        "success": True,
        "bank_balance": 0,
        "message": "Screen Time Bank balance has been reset to 0.",
    }


@app.post("/api/nintendo/add-time-manual")
async def add_time_manual(payload: ManualTimeInjection):
    """Directly send extra playtime to a Nintendo Switch console on demand."""
    db_path = get_db_path()

    if not state.nintendo.is_connected:
        # Try reconnecting
        await state.nintendo.connect_with_token()

    if not state.nintendo.is_connected:
        raise HTTPException(
            status_code=503,
            detail=f"Nintendo Switch is not connected: {state.nintendo.last_error or 'Check diagnostics'}",
        )

    target_id = payload.device_id or state.selected_device_id
    res = await state.nintendo.add_extra_time(target_id, payload.minutes)

    if not res.get("success"):
        raise HTTPException(status_code=502, detail=res.get("message", "Failed to add time to Switch."))

    await record_reward_event(
        minutes=payload.minutes,
        questions=0,
        synced=True,
        device_id=res.get("device_id"),
        note=f"Direct Manual Boost: +{payload.minutes}m to {res.get('device_name')}",
        db_path=db_path,
    )

    return res


@app.post("/api/nintendo/cancel-extra-time")
async def cancel_extra_time_endpoint():
    """Cancel and reset any bonus playtime active on the Nintendo Switch for today."""
    if not state.nintendo.is_connected:
        await state.nintendo.connect_with_token()

    if not state.nintendo.is_connected:
        raise HTTPException(
            status_code=503,
            detail=f"Nintendo Switch is not connected: {state.nintendo.last_error or 'Check diagnostics'}",
        )

    res = await state.nintendo.cancel_extra_time(state.selected_device_id)
    return res


@app.post("/api/allowance/reset-today")
@app.post("/api/rewards/reset-today")
async def reset_today_allowance_endpoint():
    """Reset today's claimed rewards and bonus allowance back to 0 for a fresh start."""
    db_path = get_db_path()

    # 1. Reset today's reward records in JSON store
    cleared_count = await reset_today_rewards(db_path)

    # 2. Reset session unclaimed correct questions to 0
    state.unclaimed_correct_count = 0

    # 3. If Nintendo is connected, reset extra playing time on the console
    nintendo_res = None
    if state.nintendo.is_connected:
        try:
            nintendo_res = await state.nintendo.cancel_extra_time(state.selected_device_id)
        except Exception as err:
            logger.warning("Failed to reset extra time on Switch: %s", err)

    logger.info(
        "Reset today's allowance. Cleared %d local reward records. Nintendo reset: %s",
        cleared_count,
        nintendo_res.get("success") if nintendo_res else "not connected",
    )

    today_awarded = await get_today_rewarded_minutes(db_path)
    bank_balance = await get_bank_balance(db_path)
    devices = await state.nintendo.get_devices() if state.nintendo.is_connected else []

    return {
        "status": "ok",
        "success": True,
        "message": "Today's reward allowance and Switch bonus time have been reset.",
        "cleared_records": cleared_count,
        "today_rewarded_minutes": today_awarded,
        "unclaimed_correct": state.unclaimed_correct_count,
        "unclaimed_correct_count": state.unclaimed_correct_count,
        "bank_balance": bank_balance,
        "devices": devices,
    }


@app.post("/api/rewards/claim")
async def manual_claim_reward():
    """Manual claim button for earned milestone."""
    db_path = get_db_path()
    settings = await get_all_settings(db_path)

    mins_to_grant = settings["minutes_per_reward"]
    today_awarded = await get_today_rewarded_minutes(db_path)
    max_daily = settings["max_daily_reward_minutes"]

    if max_daily > 0 and (today_awarded + mins_to_grant) > max_daily:
        mins_to_grant = max(0, max_daily - today_awarded)

    if mins_to_grant <= 0:
        raise HTTPException(status_code=400, detail="Daily reward limit reached for today.")

    synced = False
    nintendo_msg = "Added to Screen Time Bank."
    new_bank = await adjust_bank_minutes(mins_to_grant, "Manual claim button", db_path)

    if state.nintendo.is_connected:
        add_res = await state.nintendo.add_extra_time(
            device_id=state.selected_device_id, minutes=mins_to_grant
        )
        synced = add_res.get("success", False)
        nintendo_msg = (
            f"Added +{mins_to_grant} mins to {add_res.get('device_name', 'Switch')}!"
            if synced
            else f"Saved to bank (Switch error: {add_res.get('message')})"
        )

    await record_reward_event(
        minutes=mins_to_grant,
        questions=0,
        synced=synced,
        device_id=state.selected_device_id,
        note=f"Claim: {nintendo_msg}",
        db_path=db_path,
    )

    return {
        "success": True,
        "minutes": mins_to_grant,
        "synced": synced,
        "bank_balance": new_bank,
        "message": nintendo_msg,
    }


@app.get("/api/stats")
async def get_stats():
    """Return times tables mastery matrix (2 to 12) and reward history."""
    db_path = get_db_path()
    matrix = state.engine.get_mastery_matrix()
    recent = await get_recent_rewards(limit=15, db_path=db_path)
    today_awarded = await get_today_rewarded_minutes(db_path)
    bank_balance = await get_bank_balance(db_path)

    total_facts = len(state.engine.facts)
    mastered = sum(1 for f in state.engine.facts.values() if f.is_mastered)
    practiced = sum(1 for f in state.engine.facts.values() if f.attempts > 0)

    return {
        "matrix": matrix,
        "summary": {
            "total_facts": total_facts,
            "mastered_facts": mastered,
            "practiced_facts": practiced,
            "mastery_percentage": round((mastered / max(1, total_facts)) * 100),
            "today_awarded_minutes": today_awarded,
            "bank_balance": bank_balance,
        },
        "recent_rewards": recent,
    }


@app.get("/api/settings")
async def get_settings():
    """Fetch current app configuration."""
    db_path = get_db_path()
    settings = await get_all_settings(db_path)
    settings["selected_device_id"] = state.selected_device_id
    return settings


@app.post("/api/settings")
async def update_settings(payload: SettingsUpdate):
    """Update application settings."""
    db_path = get_db_path()

    if payload.questions_per_reward is not None:
        await set_setting("questions_per_reward", str(payload.questions_per_reward), db_path)
    if payload.minutes_per_reward is not None:
        await set_setting("minutes_per_reward", str(payload.minutes_per_reward), db_path)
    if payload.max_daily_reward_minutes is not None:
        await set_setting("max_daily_reward_minutes", str(payload.max_daily_reward_minutes), db_path)
    if payload.speed_threshold_ms is not None:
        await set_setting("speed_threshold_ms", str(payload.speed_threshold_ms), db_path)
        state.engine.speed_threshold_ms = payload.speed_threshold_ms
    if payload.active_tables is not None:
        await set_setting("active_tables", json.dumps(payload.active_tables), db_path)
        state.engine.set_active_tables(payload.active_tables)
    if payload.selected_device_id is not None:
        state.selected_device_id = payload.selected_device_id
    if payload.reward_mode is not None:
        await set_setting("reward_mode", payload.reward_mode, db_path)
    if payload.exclude_twos is not None:
        await set_setting("exclude_twos", "true" if payload.exclude_twos else "false", db_path)
        state.engine.exclude_twos = payload.exclude_twos
    if payload.exclude_tens is not None:
        await set_setting("exclude_tens", "true" if payload.exclude_tens else "false", db_path)
        state.engine.exclude_tens = payload.exclude_tens
    elevens_flag = (
        payload.exclude_elevens_single_digit
        if payload.exclude_elevens_single_digit is not None
        else payload.exclude_elevens_two_digit
    )
    if elevens_flag is not None:
        await set_setting("exclude_elevens_single_digit", "true" if elevens_flag else "false", db_path)
        await set_setting("exclude_elevens_two_digit", "true" if elevens_flag else "false", db_path)
        state.engine.exclude_elevens_single_digit = elevens_flag

    return {"status": "ok", "settings": await get_all_settings(db_path)}


# Diagnostic & Logging Endpoints

@app.get("/api/debug/logs")
async def get_debug_logs():
    """Return in-memory log buffer for frontend debug viewer."""
    return {"logs": get_recent_logs(150)}


@app.delete("/api/debug/logs")
async def clear_debug_logs():
    """Clear memory log buffer."""
    clear_logs()
    return {"status": "cleared"}


@app.post("/api/debug/test-nintendo")
async def run_nintendo_diagnostic():
    """Run active Nintendo connection check and return diagnostic report."""
    logger.info("Starting on-demand Nintendo connection diagnostic...")
    report = await state.nintendo.diagnose_connection()
    return report


@app.get("/api/debug/log-file")
async def download_log_file():
    """Download full log file."""
    log_path = Path("data/app_debug.log")
    if log_path.exists():
        return FileResponse(log_path, filename="app_debug.log", media_type="text/plain")
    return PlainTextResponse("No log file found yet.")


# Nintendo Authentication Endpoints

@app.get("/api/nintendo/login-url")
async def get_nintendo_login_url():
    """Generate Nintendo OAuth URL for interactive web login."""
    try:
        url = await state.nintendo.start_interactive_login()
        return {"login_url": url}
    except Exception as err:
        logger.exception("Failed to start Nintendo interactive login: %s", err)
        raise HTTPException(status_code=500, detail=str(err))


@app.post("/api/nintendo/complete-login")
async def complete_nintendo_login(payload: LoginCompletion):
    """Exchange Nintendo redirect URL for session token and connect."""
    try:
        token = await state.nintendo.complete_interactive_login(payload.response_url)
        from scripts.test_nintendo import save_session_token_to_env
        save_session_token_to_env(token)
        devices = await state.nintendo.get_devices()
        return {"status": "ok", "connected": True, "devices": devices}
    except Exception as err:
        logger.exception("Complete Nintendo login failed: %s", err)
        raise HTTPException(status_code=400, detail=f"Login failed: {err}")


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles class that enforces no-cache headers for fresh local development."""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# Static Files & Root
app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def cli():
    """Entry point for `uv run switchmath`."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="SwitchMath - Times Tables with Nintendo Switch Rewards")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Host interface (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="Port to listen on (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    cli()



