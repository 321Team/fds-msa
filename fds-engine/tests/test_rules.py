"""
Unit tests for FDS rule evaluation logic (app/rules.py).

These are pure-function tests: no DB, no network, no FastAPI app needed.
Threshold values mirror app/rules.py as of 2026-09 (draft, subject to change
per team decision — see module docstring in rules.py).
"""
from datetime import datetime, timezone

from app.rules import (
    evaluate_r01,
    evaluate_r02,
    evaluate_r04,
    evaluate_r07,
    evaluate_all,
)


# --- R01: 10분 내 인출 N회 이상 ---

def test_r01_triggers_at_threshold():
    triggered, detail = evaluate_r01("withdrawal", {"recent_withdrawal_count_10m": 3})
    assert triggered is True
    assert detail is not None


def test_r01_not_triggered_below_threshold():
    triggered, detail = evaluate_r01("withdrawal", {"recent_withdrawal_count_10m": 2})
    assert triggered is False
    assert detail is None


def test_r01_ignores_non_withdrawal_transactions():
    triggered, _ = evaluate_r01("deposit", {"recent_withdrawal_count_10m": 99})
    assert triggered is False


def test_r01_missing_context_defaults_to_zero():
    triggered, _ = evaluate_r01("withdrawal", {})
    assert triggered is False


# --- R02: 고액 거래 ---

def test_r02_triggers_on_high_amount():
    triggered, detail = evaluate_r02(3_000_000)
    assert triggered is True
    assert detail is not None


def test_r02_not_triggered_below_threshold():
    triggered, _ = evaluate_r02(2_999_999)
    assert triggered is False


# --- R04: 심야(KST 01:00~05:00) 고액 거래 ---

def test_r04_triggers_inside_late_night_window_kst():
    # KST 03:00 == UTC 18:00 (전날)
    occurred_at = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
    triggered, detail = evaluate_r04(occurred_at, 1_000_000)
    assert triggered is True
    assert detail is not None


def test_r04_not_triggered_outside_window():
    occurred_at = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)  # KST 17:00
    triggered, _ = evaluate_r04(occurred_at, 1_000_000)
    assert triggered is False


def test_r04_not_triggered_inside_window_below_amount():
    occurred_at = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)  # KST 03:00
    triggered, _ = evaluate_r04(occurred_at, 999_999)
    assert triggered is False


def test_r04_naive_datetime_is_treated_as_utc():
    # naive datetime -> UTC로 간주 -> KST 03:00 (심야)
    occurred_at = datetime(2026, 9, 15, 18, 0)
    triggered, _ = evaluate_r04(occurred_at, 1_000_000)
    assert triggered is True


def test_r04_window_boundary_end_hour_excluded():
    # KST 05:00 정각은 윈도우 밖 (R04_LATE_NIGHT_END_HOUR = 5, exclusive)
    occurred_at = datetime(2026, 9, 15, 20, 0, tzinfo=timezone.utc)  # KST 05:00
    triggered, _ = evaluate_r04(occurred_at, 1_000_000)
    assert triggered is False


# --- R07: 1시간 내 소액 분산 이체 ---

def test_r07_triggers_on_repeated_small_transfers():
    context = {"recent_transfer_count_1h": 3, "recent_transfer_sum_1h": 2_000_000}
    triggered, detail = evaluate_r07("transfer", context)
    assert triggered is True
    assert detail is not None


def test_r07_ignores_non_transfer_transactions():
    context = {"recent_transfer_count_1h": 99, "recent_transfer_sum_1h": 99_000_000}
    triggered, _ = evaluate_r07("withdrawal", context)
    assert triggered is False


def test_r07_not_triggered_when_only_count_meets_threshold():
    context = {"recent_transfer_count_1h": 3, "recent_transfer_sum_1h": 1_000_000}
    triggered, _ = evaluate_r07("transfer", context)
    assert triggered is False


# --- evaluate_all: Contract 계약 (응답 형태·순서) ---

def test_evaluate_all_returns_four_rules_in_fixed_order():
    payload = {
        "transaction_type": "withdrawal",
        "amount": 5_000_000,
        "occurred_at": "2026-09-16T12:00:00+09:00",  # 낮 시간, R04 미해당
        "context": {"recent_withdrawal_count_10m": 3},
    }
    results = evaluate_all(payload)
    assert [r["rule_id"] for r in results] == ["R01", "R02", "R04", "R07"]
    assert results[0]["triggered"] is True  # R01: count>=3
    assert results[1]["triggered"] is True  # R02: amount>=3,000,000
    assert results[2]["triggered"] is False  # R04: 낮 시간
    assert results[3]["triggered"] is False  # R07: withdrawal이라 해당 없음


def test_evaluate_all_missing_context_does_not_raise():
    payload = {
        "transaction_type": "deposit",
        "amount": 1000,
        "occurred_at": "2026-09-16T12:00:00+09:00",
        # context 키 자체가 없는 경우 (transaction-api 구버전 호출 호환)
    }
    results = evaluate_all(payload)
    assert len(results) == 4
    assert all(r["triggered"] is False for r in results)
