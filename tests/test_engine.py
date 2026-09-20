"""Unit tests for the Delayed Repetition Learning Engine."""

import pytest
from app.learning.engine import RepetitionEngine


def test_engine_initialization():
    """Verify that all 121 pairs (2x2 to 12x12) are created."""
    engine = RepetitionEngine(min_table=2, max_table=12)
    assert len(engine.facts) == 11 * 11
    assert "2x2" in engine.facts
    assert "12x12" in engine.facts
    assert "7x8" in engine.facts


def test_fast_correct_answer():
    """A quick and correct answer should promote box and not schedule retry."""
    engine = RepetitionEngine(speed_threshold_ms=4000.0)
    result = engine.record_answer(factor_a=7, factor_b=8, user_answer=56, latency_ms=1500.0)

    assert result["is_correct"] is True
    assert result["evaluation"] == "fast"
    assert result["scheduled_for_retry"] is False
    assert result["new_box"] == 1


def test_incorrect_answer_schedules_delayed_retry():
    """An incorrect answer drops box level and schedules a delayed retry."""
    engine = RepetitionEngine(retry_delay_questions=3)
    # Question count starts at 0
    q1 = engine.get_next_question()
    assert engine.total_questions_served == 1

    result = engine.record_answer(factor_a=6, factor_b=7, user_answer=40, latency_ms=2000.0)
    assert result["is_correct"] is False
    assert result["evaluation"] == "incorrect"
    assert result["scheduled_for_retry"] is True
    assert result["due_in_questions"] == 3
    assert len(engine.retry_queue) == 1
    # Due at question 1 + 3 = 4
    assert engine.retry_queue[0].due_at_question_index == 4


def test_slow_correct_answer_schedules_retry():
    """A correct but slow (> threshold) answer should schedule delayed retry for speed practice."""
    engine = RepetitionEngine(speed_threshold_ms=3000.0, retry_delay_questions=2)
    engine.get_next_question()

    result = engine.record_answer(factor_a=9, factor_b=6, user_answer=54, latency_ms=4500.0)
    assert result["is_correct"] is True
    assert result["evaluation"] == "slow"
    assert result["scheduled_for_retry"] is True
    assert len(engine.retry_queue) == 1


def test_delayed_retry_served_at_due_turn():
    """Verify that a scheduled retry is served when its turn arrives."""
    engine = RepetitionEngine(retry_delay_questions=2)
    # Serve Q1
    engine.get_next_question()  # total_questions_served = 1
    # Fail 8x8
    engine.record_answer(8, 8, user_answer=60, latency_ms=2000.0)
    # Retry scheduled for total_questions_served (1) + 2 = 3

    # Serve Q2
    a2, b2, r2 = engine.get_next_question()  # total_questions_served = 2
    # Q2 should not be the retry yet
    assert (a2, b2) != (8, 8) or r2 != "retry_incorrect"

    # Serve Q3 - now the delayed retry is due!
    a3, b3, r3 = engine.get_next_question()  # total_questions_served = 3
    assert (a3, b3) == (8, 8)
    assert r3 == "retry_incorrect"
    # Retry queue should now be empty
    assert len(engine.retry_queue) == 0


def test_active_tables_filter():
    """Filtering to specific tables should only serve facts where both factors are in active tables."""
    engine = RepetitionEngine(active_tables=[3, 5])
    # 2 is not active, so 2x3 and 3x2 must NOT be allowed!
    assert not engine.is_fact_allowed(2, 3)
    assert not engine.is_fact_allowed(3, 2)
    assert not engine.is_fact_allowed(2, 5)
    assert engine.is_fact_allowed(3, 5)
    assert engine.is_fact_allowed(5, 3)
    assert engine.is_fact_allowed(3, 3)
    assert engine.is_fact_allowed(5, 5)

    for _ in range(30):
        a, b, _ = engine.get_next_question()
        assert a in (3, 5) and b in (3, 5)


def test_single_active_table():
    """Selecting a single table (e.g. 7s) allows practicing facts for that table."""
    engine = RepetitionEngine(active_tables=[7])
    assert engine.is_fact_allowed(7, 3)
    assert engine.is_fact_allowed(3, 7)
    assert engine.is_fact_allowed(7, 2)
    assert not engine.is_fact_allowed(3, 4)

    # When exclude_twos is also True, 7x2 and 2x7 are excluded
    engine_no_2 = RepetitionEngine(active_tables=[7], exclude_twos=True)
    assert not engine_no_2.is_fact_allowed(7, 2)
    assert not engine_no_2.is_fact_allowed(2, 7)
    assert engine_no_2.is_fact_allowed(7, 3)


def test_exclude_twos_filter():
    """Verify that 2x tables are excluded when exclude_twos is True."""
    engine = RepetitionEngine(exclude_twos=True)
    assert not engine.is_fact_allowed(2, 3)
    assert not engine.is_fact_allowed(3, 2)
    assert not engine.is_fact_allowed(2, 2)
    assert engine.is_fact_allowed(3, 3)

    candidates = engine.get_candidate_facts()
    for f in candidates:
        assert f.factor_a != 2 and f.factor_b != 2

    for _ in range(50):
        a, b, _ = engine.get_next_question()
        assert a != 2 and b != 2


def test_mastery_matrix():
    """Matrix should return 11 rows each containing 11 facts."""
    engine = RepetitionEngine()
    matrix = engine.get_mastery_matrix()
    assert len(matrix) == 11
    assert len(matrix[0]["facts"]) == 11
    assert matrix[0]["factor"] == 2


def test_exclude_tens_filter():
    """Verify that 10x tables are excluded when exclude_tens is True."""
    engine = RepetitionEngine(exclude_tens=True)
    assert not engine.is_fact_allowed(10, 5)
    assert not engine.is_fact_allowed(7, 10)
    assert not engine.is_fact_allowed(10, 10)
    assert engine.is_fact_allowed(9, 9)

    candidates = engine.get_candidate_facts()
    for f in candidates:
        assert f.factor_a != 10 and f.factor_b != 10

    for _ in range(50):
        a, b, _ = engine.get_next_question()
        assert a != 10 and b != 10


def test_exclude_elevens_single_digit_filter():
    """Verify that 11x tables with single-digit numbers are excluded while two-digit 11s remain."""
    engine = RepetitionEngine(exclude_elevens_single_digit=True)
    # Single-digit combos excluded
    assert not engine.is_fact_allowed(11, 2)
    assert not engine.is_fact_allowed(2, 11)
    assert not engine.is_fact_allowed(7, 11)
    assert not engine.is_fact_allowed(11, 7)
    assert not engine.is_fact_allowed(11, 9)
    assert not engine.is_fact_allowed(9, 11)

    # Two-digit combos allowed
    assert engine.is_fact_allowed(11, 10)
    assert engine.is_fact_allowed(10, 11)
    assert engine.is_fact_allowed(11, 11)
    assert engine.is_fact_allowed(11, 12)
    assert engine.is_fact_allowed(12, 11)

    # When active_tables is only [11]
    engine_11 = RepetitionEngine(active_tables=[11], exclude_elevens_single_digit=True)
    candidates_11 = engine_11.get_candidate_facts()
    for f in candidates_11:
        assert not ((f.factor_a == 11 and f.factor_b < 10) or (f.factor_b == 11 and f.factor_a < 10))

    for _ in range(30):
        a, b, _ = engine_11.get_next_question()
        assert not ((a == 11 and b < 10) or (b == 11 and a < 10))


def test_mastery_matrix_active_flag():
    """Mastery matrix should accurately reflect is_active based on exclusion settings."""
    engine = RepetitionEngine(exclude_twos=True, exclude_tens=True, exclude_elevens_single_digit=True)
    matrix = engine.get_mastery_matrix()

    for row in matrix:
        for fact in row["facts"]:
            a, b = fact["a"], fact["b"]
            if a == 2 or b == 2:
                assert fact["is_active"] is False
            elif a == 10 or b == 10:
                assert fact["is_active"] is False
            elif (a == 11 and b < 10) or (b == 11 and a < 10):
                assert fact["is_active"] is False
            else:
                assert fact["is_active"] is True


