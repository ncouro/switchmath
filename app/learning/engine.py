"""Times Tables Delayed Repetition Learning Engine.

Handles generation of times table facts (2 to 12), answer grading,
latency evaluation, and Leitner-style delayed repetition scheduling.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FactRecord:
    """Learning state of an individual multiplication fact (e.g. 7 x 8)."""

    factor_a: int
    factor_b: int
    box: int = 0  # Leitner box: 0 (new) to 5 (mastered)
    consecutive_correct: int = 0
    attempts: int = 0
    wrong_count: int = 0
    last_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    last_seen: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.factor_a}x{self.factor_b}"

    @property
    def product(self) -> int:
        return self.factor_a * self.factor_b

    @property
    def is_mastered(self) -> bool:
        return self.box >= 4 and self.avg_latency_ms > 0 and self.avg_latency_ms < 3500


@dataclass
class ScheduledRetry:
    """A fact scheduled to reappear after a delay of N questions."""

    factor_a: int
    factor_b: int
    due_at_question_index: int
    reason: str  # "incorrect" or "slow"


class RepetitionEngine:
    """Delayed repetition engine for times tables (2 to 12)."""

    def __init__(
        self,
        min_table: int = 2,
        max_table: int = 12,
        speed_threshold_ms: float = 4000.0,
        retry_delay_questions: int = 3,
        active_tables: Optional[List[int]] = None,
        exclude_tens: bool = False,
        exclude_elevens_single_digit: bool = False,
        exclude_elevens_two_digit: Optional[bool] = None,
        exclude_twos: bool = False,
    ):
        self.min_table = min_table
        self.max_table = max_table
        self.speed_threshold_ms = speed_threshold_ms
        self.retry_delay_questions = retry_delay_questions
        self.active_tables = set(active_tables) if active_tables else set(range(min_table, max_table + 1))
        self.exclude_tens = exclude_tens
        self.exclude_elevens_single_digit = exclude_elevens_single_digit or (exclude_elevens_two_digit is True)
        self.exclude_twos = exclude_twos

        # Memory store: "a x b" -> FactRecord
        self.facts: Dict[str, FactRecord] = {}
        self._init_all_facts()

        # Delayed repetition queue: list of ScheduledRetry
        self.retry_queue: List[ScheduledRetry] = []
        self.total_questions_served: int = 0

    @property
    def exclude_elevens_two_digit(self) -> bool:
        """Alias for backward compatibility."""
        return self.exclude_elevens_single_digit

    @exclude_elevens_two_digit.setter
    def exclude_elevens_two_digit(self, value: bool) -> None:
        self.exclude_elevens_single_digit = value

    def _init_all_facts(self) -> None:
        """Initialize all 121 multiplication combinations (2..12)."""
        for a in range(self.min_table, self.max_table + 1):
            for b in range(self.min_table, self.max_table + 1):
                key = f"{a}x{b}"
                if key not in self.facts:
                    self.facts[key] = FactRecord(factor_a=a, factor_b=b)

    def set_active_tables(self, tables: List[int]) -> None:
        """Filter practice to specific tables (e.g. [6, 7, 8])."""
        valid = [t for t in tables if self.min_table <= t <= self.max_table]
        if valid:
            self.active_tables = set(valid)

    def is_fact_allowed(self, a: int, b: int) -> bool:
        """Check if a fact is allowed based on active tables and exclusion filters."""
        # Active tables constraint
        if len(self.active_tables) == 1:
            target = next(iter(self.active_tables))
            if a != target and b != target:
                return False
        else:
            if a not in self.active_tables or b not in self.active_tables:
                return False

        # Easy 2x tables filter (doubling)
        if self.exclude_twos and (a == 2 or b == 2):
            return False
        # Easy 10x tables filter
        if self.exclude_tens and (a == 10 or b == 10):
            return False
        # 11x tables with single-digit numbers (11x2 ... 11x9 and commutes)
        if self.exclude_elevens_single_digit:
            if (a == 11 and b < 10) or (b == 11 and a < 10):
                return False
        return True

    def get_candidate_facts(self) -> List[FactRecord]:
        """Get all facts relevant to currently active tables and filters."""
        return [
            fact for fact in self.facts.values()
            if self.is_fact_allowed(fact.factor_a, fact.factor_b)
        ]

    def get_next_question(self) -> Tuple[int, int, str]:
        """Select the next question using delayed repetition logic.

        Returns:
            (factor_a, factor_b, prompt_reason)
            where prompt_reason indicates why this question was selected:
            'retry_delayed' | 'practice_weak' | 'spaced_review' | 'new_learning'
        """
        self.total_questions_served += 1
        current_index = self.total_questions_served

        # 1. Check if any delayed retries are due (and still allowed)
        due_retries = [
            r for r in self.retry_queue
            if r.due_at_question_index <= current_index and self.is_fact_allowed(r.factor_a, r.factor_b)
        ]
        if due_retries:
            # Pop the earliest due retry
            chosen_retry = due_retries[0]
            self.retry_queue.remove(chosen_retry)
            reason = f"retry_{chosen_retry.reason}"
            return chosen_retry.factor_a, chosen_retry.factor_b, reason

        candidates = self.get_candidate_facts()
        if not candidates:
            # Fallback to any allowed fact
            allowed = [f for f in self.facts.values() if self.is_fact_allowed(f.factor_a, f.factor_b)]
            if allowed:
                f = random.choice(allowed)
                return f.factor_a, f.factor_b, "random_fallback"
            non_two = [f for f in self.facts.values() if f.factor_a != 2 and f.factor_b != 2]
            if non_two and (self.exclude_twos or 2 not in self.active_tables):
                f = random.choice(non_two)
                return f.factor_a, f.factor_b, "random_fallback"
            return 2, 2, "random_fallback"

        # 2. Prioritize unpracticed facts (box 0)
        unpracticed = [f for f in candidates if f.attempts == 0]
        if unpracticed and random.random() < 0.4:
            chosen = random.choice(unpracticed)
            return chosen.factor_a, chosen.factor_b, "new_learning"

        # 3. Weighted selection based on difficulty & latency
        # Higher weight = lower box + high error count + slow latency
        weights = []
        for f in candidates:
            base = max(1, 6 - f.box) * 3
            error_penalty = f.wrong_count * 2
            speed_penalty = 3 if f.avg_latency_ms > self.speed_threshold_ms else 0
            # Recency penalty to avoid asking back-to-back
            recency_discount = 0.1 if (time.time() - f.last_seen < 10) else 1.0
            weight = (base + error_penalty + speed_penalty) * recency_discount
            weights.append(weight)

        chosen = random.choices(candidates, weights=weights, k=1)[0]
        reason = "spaced_review" if chosen.box > 0 else "practice_weak"
        return chosen.factor_a, chosen.factor_b, reason

    def record_answer(
        self,
        factor_a: int,
        factor_b: int,
        user_answer: int,
        latency_ms: float,
    ) -> Dict[str, Any]:
        """Grade the answer, update Leitner box and schedule delayed retries.

        Args:
            factor_a: first factor
            factor_b: second factor
            user_answer: submitted answer
            latency_ms: time taken in milliseconds

        Returns:
            Grading evaluation dictionary.
        """
        key = f"{factor_a}x{factor_b}"
        fact = self.facts.get(key)
        if not fact:
            fact = FactRecord(factor_a=factor_a, factor_b=factor_b)
            self.facts[key] = fact

        correct_answer = factor_a * factor_b
        is_correct = (user_answer == correct_answer)
        is_slow = (latency_ms > self.speed_threshold_ms)

        fact.attempts += 1
        fact.last_seen = time.time()
        fact.last_latency_ms = latency_ms

        # Exponential moving average for latency
        if fact.avg_latency_ms == 0:
            fact.avg_latency_ms = latency_ms
        else:
            fact.avg_latency_ms = 0.7 * fact.avg_latency_ms + 0.3 * latency_ms

        scheduled_for_retry = False
        retry_delay = self.retry_delay_questions

        if not is_correct:
            fact.wrong_count += 1
            fact.consecutive_correct = 0
            fact.box = max(0, fact.box - 2)  # Drop box level
            # Schedule delayed retry in N questions!
            self.retry_queue.append(
                ScheduledRetry(
                    factor_a=factor_a,
                    factor_b=factor_b,
                    due_at_question_index=self.total_questions_served + retry_delay,
                    reason="incorrect",
                )
            )
            scheduled_for_retry = True
            evaluation = "incorrect"
            message = f"Incorrect. {factor_a} × {factor_b} = {correct_answer}. We'll practice this one again soon!"

        elif is_slow:
            # Correct, but hesitated/slow
            fact.consecutive_correct += 1
            # Box increases slowly if hesitant
            fact.box = min(3, fact.box + 1)
            # Schedule delayed retry to solidify speed
            self.retry_queue.append(
                ScheduledRetry(
                    factor_a=factor_a,
                    factor_b=factor_b,
                    due_at_question_index=self.total_questions_served + retry_delay,
                    reason="slow",
                )
            )
            scheduled_for_retry = True
            evaluation = "slow"
            seconds = round(latency_ms / 1000.0, 1)
            message = f"Correct, but took {seconds}s. Let's make it lightning fast!"

        else:
            # Correct and Fast!
            fact.consecutive_correct += 1
            fact.box = min(5, fact.box + 1)
            evaluation = "fast"
            seconds = round(latency_ms / 1000.0, 1)
            message = f"Awesome! Lightning fast ({seconds}s)!"

        return {
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "evaluation": evaluation,
            "message": message,
            "latency_ms": latency_ms,
            "new_box": fact.box,
            "scheduled_for_retry": scheduled_for_retry,
            "due_in_questions": retry_delay if scheduled_for_retry else None,
        }

    def get_mastery_matrix(self) -> List[Dict[str, Any]]:
        """Return the complete 2..12 times table mastery grid for visualization."""
        matrix = []
        for a in range(self.min_table, self.max_table + 1):
            row = []
            for b in range(self.min_table, self.max_table + 1):
                key = f"{a}x{b}"
                fact = self.facts.get(key)
                if not fact or fact.attempts == 0:
                    status = "unseen"
                elif fact.box >= 4 and fact.avg_latency_ms < self.speed_threshold_ms:
                    status = "mastered"
                elif fact.box >= 2:
                    status = "learning"
                elif fact.avg_latency_ms > self.speed_threshold_ms:
                    status = "slow"
                else:
                    status = "struggling"

                row.append({
                    "a": a,
                    "b": b,
                    "product": a * b,
                    "box": fact.box if fact else 0,
                    "attempts": fact.attempts if fact else 0,
                    "wrong_count": fact.wrong_count if fact else 0,
                    "avg_latency_ms": round(fact.avg_latency_ms) if fact else 0,
                    "status": status,
                    "is_active": self.is_fact_allowed(a, b),
                })
            matrix.append({"factor": a, "facts": row})
        return matrix

