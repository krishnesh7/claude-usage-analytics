from datetime import datetime, timezone
import pytest
from claude_usage.db import parse_until


def test_parse_until_none_returns_none(db):
    assert parse_until(None) is None


def test_parse_until_all_returns_none(db):
    assert parse_until("all") is None


def test_parse_until_empty_returns_none(db):
    assert parse_until("") is None


def test_parse_until_date_only_sets_end_of_day(db):
    result = parse_until("2026-05-29")
    assert result is not None
    assert result.year == 2026
    assert result.month == 5
    assert result.day == 29
    assert result.hour == 23
    assert result.minute == 59
    assert result.second == 59
    assert result.tzinfo is not None


def test_parse_until_iso_datetime_preserved(db):
    result = parse_until("2026-05-15T10:00:00")
    assert result is not None
    assert result.year == 2026
    assert result.month == 5
    assert result.day == 15
    assert result.hour == 10


def test_parse_until_invalid_returns_none(db):
    assert parse_until("bogus") is None
