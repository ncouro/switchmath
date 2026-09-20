"""Integration tests for the FastAPI Web Application endpoints."""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_api.json"
    monkeypatch.setenv("DATABASE_PATH", str(test_db))
    with TestClient(app) as test_client:
        yield test_client


def test_root_serves_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Times Tables Quest" in response.text


def test_api_status(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "nintendo_connected" in data
    assert "session" in data
    assert "rewards" in data
    assert "active_tables" in data


def test_api_quiz_flow(client):
    # 1. Fetch next question
    next_res = client.get("/api/quiz/next")
    assert next_res.status_code == 200
    q = next_res.json()
    assert 2 <= q["factor_a"] <= 12
    assert 2 <= q["factor_b"] <= 12

    # 2. Submit correct fast answer
    correct_val = q["factor_a"] * q["factor_b"]
    ans_res = client.post(
        "/api/quiz/answer",
        json={
            "factor_a": q["factor_a"],
            "factor_b": q["factor_b"],
            "user_answer": correct_val,
            "latency_ms": 1500.0,
        },
    )
    assert ans_res.status_code == 200
    ans_data = ans_res.json()
    assert ans_data["evaluation"]["is_correct"] is True
    assert ans_data["evaluation"]["evaluation"] == "fast"

    # 3. Submit incorrect answer
    wrong_val = correct_val + 1
    wrong_res = client.post(
        "/api/quiz/answer",
        json={
            "factor_a": q["factor_a"],
            "factor_b": q["factor_b"],
            "user_answer": wrong_val,
            "latency_ms": 2000.0,
        },
    )
    assert wrong_res.status_code == 200
    w_data = wrong_res.json()
    assert w_data["evaluation"]["is_correct"] is False
    assert w_data["evaluation"]["scheduled_for_retry"] is True


def test_api_stats_matrix(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "matrix" in data
    assert len(data["matrix"]) == 11
    assert "summary" in data
    assert data["summary"]["total_facts"] == 121


def test_api_settings_update(client):
    update_res = client.post(
        "/api/settings",
        json={
            "questions_per_reward": 8,
            "minutes_per_reward": 6,
            "speed_threshold_ms": 3500.0,
            "active_tables": [3, 4, 5],
        },
    )
    assert update_res.status_code == 200
    updated = update_res.json()["settings"]
    assert updated["questions_per_reward"] == 8
    assert updated["minutes_per_reward"] == 6
    assert updated["speed_threshold_ms"] == 3500.0
    assert updated["active_tables"] == [3, 4, 5]


def test_bank_adjust_and_balance(client):
    # Add 15 minutes to bank
    add_res = client.post(
        "/api/bank/adjust",
        json={"minutes": 15, "reason": "Test addition"},
    )
    assert add_res.status_code == 200
    data = add_res.json()
    assert data["success"] is True
    assert data["new_balance"] >= 15

    # Check status includes updated bank_balance
    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    assert status_res.json()["rewards"]["bank_balance"] >= 15

    # Deduct 5 minutes
    deduct_res = client.post(
        "/api/bank/adjust",
        json={"minutes": -5, "reason": "Test redemption"},
    )
    assert deduct_res.status_code == 200
    assert deduct_res.json()["new_balance"] == data["new_balance"] - 5


def test_bank_reset_endpoint(client):
    client.post("/api/bank/adjust", json={"minutes": 20, "reason": "Pre-reset"})
    reset_res = client.post("/api/bank/reset")
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "ok"
    assert reset_res.json()["bank_balance"] == 0

    status_res = client.get("/api/status")
    assert status_res.json()["rewards"]["bank_balance"] == 0


def test_bank_withdraw_validation(client):
    # Requesting more than available in bank (e.g. 50m when bank has 0) should fail with 400
    res = client.post("/api/bank/withdraw", json={"minutes": 50})
    assert res.status_code == 400
    assert "exceeds" in res.json()["detail"]


def test_debug_logs_endpoints(client):
    logs_res = client.get("/api/debug/logs")
    assert logs_res.status_code == 200
    assert "logs" in logs_res.json()

    clear_res = client.delete("/api/debug/logs")
    assert clear_res.status_code == 200
    assert clear_res.json()["status"] == "cleared"


def test_nintendo_diagnostic_endpoint(client):
    diag_res = client.post("/api/debug/test-nintendo")
    assert diag_res.status_code == 200
    data = diag_res.json()
    assert "auth_status" in data
    assert "steps" in data


def test_api_settings_exclude_options(client):
    """Test getting, updating, and verifying exclude_twos, exclude_tens, and exclude_elevens_single_digit."""
    # Verify default in settings
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    assert "exclude_twos" in get_res.json()
    assert "exclude_tens" in get_res.json()
    assert "exclude_elevens_single_digit" in get_res.json()

    # Update exclusion settings
    update_res = client.post(
        "/api/settings",
        json={
            "exclude_twos": True,
            "exclude_tens": True,
            "exclude_elevens_single_digit": True,
        },
    )
    assert update_res.status_code == 200
    settings = update_res.json()["settings"]
    assert settings["exclude_twos"] is True
    assert settings["exclude_tens"] is True
    assert settings["exclude_elevens_single_digit"] is True

    # Check status endpoint reflects exclusions
    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["exclude_twos"] is True
    assert status_data["exclude_tens"] is True
    assert status_data["exclude_elevens_single_digit"] is True

    # Check stats mastery matrix has inactive flags for 2s, 10s and 11s single-digit
    stats_res = client.get("/api/stats")
    assert stats_res.status_code == 200
    matrix = stats_res.json()["matrix"]
    row_2 = next(r for r in matrix if r["factor"] == 2)
    assert all(f["is_active"] is False for f in row_2["facts"])

    row_10 = next(r for r in matrix if r["factor"] == 10)
    assert all(f["is_active"] is False for f in row_10["facts"])

    row_11 = next(r for r in matrix if r["factor"] == 11)
    for f in row_11["facts"]:
        if f["b"] < 10:
            assert f["is_active"] is False
        elif f["b"] in [11, 12]:
            assert f["is_active"] is True


def test_reset_today_allowance_endpoint(client):
    res = client.post("/api/allowance/reset-today")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["today_rewarded_minutes"] == 0
    assert data["unclaimed_correct_count"] == 0

    alias_res = client.post("/api/rewards/reset-today")
    assert alias_res.status_code == 200
    alias_data = alias_res.json()
    assert alias_data["status"] == "ok"
    assert alias_data["today_rewarded_minutes"] == 0



