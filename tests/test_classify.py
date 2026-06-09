"""Tests for the SDLC stage classifier routing.

These exercise classify_text() against the real config/stage_keywords.json,
so they double as a guard that the shipped keyword rules route real-world
first-user-messages to the intended stage (and don't hijack each other).
"""
import sqlite3

import pytest

from claude_usage.classify import (
    _compile_patterns,
    classify_all,
    classify_text,
    is_overhead_message,
    load_keywords,
)


@pytest.fixture(scope="module")
def classifier():
    rules, order = load_keywords()
    return _compile_patterns(rules), order


def route(classifier, text):
    compiled, order = classifier
    return classify_text(text, compiled, order)


# --- new 'explore' stage: Q&A / investigation, not a build action -----------

@pytest.mark.parametrize("text", [
    "how to check this code",
    "can you explain me the project structure",
    "is it possible to automatically login and pull receipts",
    "why is the timestamp showing the wrong value",
    "how can I resume a conversation from the desktop app",
    "what is the correct location for this module",
])
def test_explore_questions_route_to_explore(classifier, text):
    assert route(classifier, text) == "explore"


# --- impl: conversational change/bug requests ------------------------------

@pytest.mark.parametrize("text", [
    "the timestamp shown is not correct",
    "do you see the issue with the table",
    "Can we update the chat functionality",
    "I want to add more details to the detailed tab",
    "the chart is broken after the last change",
])
def test_conversational_changes_route_to_impl(classifier, text):
    assert route(classifier, text) == "impl"


# --- requirements: project kickoff / intent --------------------------------

@pytest.mark.parametrize("text", [
    "I want to build a CAN SLIM stock-analysis platform",
    "I want to capture the actual token usage and cost",
    "# Project: AgriSync — Agriculture Data Integration POC",
    "we are building a new dashboard for spending",
])
def test_kickoff_routes_to_requirements(classifier, text):
    assert route(classifier, text) == "requirements"


# --- regression: existing stages must not be hijacked ----------------------

def test_test_stage_still_wins(classifier):
    assert route(classifier, "add a pytest fixture for coverage") == "test"


def test_deploy_stage_still_wins(classifier):
    assert route(classifier, "set up the kubernetes deployment pipeline") == "deploy"


def test_empty_message_is_adhoc(classifier):
    assert route(classifier, "") == "adhoc"


def test_no_keyword_hit_is_adhoc(classifier):
    assert route(classifier, "hello there friend") == "adhoc"


# --- reclassify: re-route already-classified sessions through new rules -----

def _seed(db, session_id, first_user_message, stage, source):
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO sessions(session_id, first_user_message) VALUES (?,?)",
        (session_id, first_user_message),
    )
    conn.execute(
        "INSERT INTO session_stage(session_id, stage, source) VALUES (?,?,?)",
        (session_id, stage, source),
    )
    conn.commit()
    conn.close()


def _stage_of(db, session_id):
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT stage, source FROM session_stage WHERE session_id=?", (session_id,)
    ).fetchone()
    conn.close()
    return row


def test_reclassify_reroutes_stale_classifier_rows(db):
    # Was bucketed 'adhoc' under the old narrow rules; now matches 'explore'.
    _seed(db, "s1", "how to check this code", "adhoc", "classifier")
    classify_all(reclassify=True)
    assert _stage_of(db, "s1")[0] == "explore"


def test_reclassify_preserves_non_classifier_sources(db):
    # Parser-authored overhead rows must survive a reclassify.
    _seed(db, "s2", "/usage report please", "_tracker_overhead_", "overhead_detect")
    classify_all(reclassify=True)
    stage, source = _stage_of(db, "s2")
    assert stage == "_tracker_overhead_"
    assert source == "overhead_detect"


def test_default_classify_leaves_existing_rows_untouched(db):
    # Without reclassify, an already-classified session is not re-evaluated.
    _seed(db, "s3", "how to check this code", "adhoc", "classifier")
    classify_all()
    assert _stage_of(db, "s3")[0] == "adhoc"


# --- memory-overhead content detection -------------------------------------

@pytest.mark.parametrize("text", [
    "You are summarizing a Claude Code session for a daily memory log.",
    "Apply maximum non-destructive compression. Rules:\n- Keep ALL facts",
    "You are a memory consolidation agent. Your job is mechanical compression",
])
def test_memory_agent_messages_are_overhead(text):
    assert is_overhead_message(text) is True


@pytest.mark.parametrize("text", [
    "You are my engineering partner building a CAN SLIM platform",
    "how to check this code",
    "implement the dashboard panels",
    "",
])
def test_real_messages_are_not_overhead(text):
    assert is_overhead_message(text) is False


def test_classifier_buckets_overhead_message_as_tracker_overhead(db):
    # A .remember background agent the parser didn't flag must still roll up
    # under _tracker_overhead_, not pollute a build stage.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO sessions(session_id, first_user_message, is_tracker_overhead) "
        "VALUES (?,?,0)",
        ("ovh1", "You are summarizing a Claude Code session for a daily memory log."),
    )
    conn.commit()
    conn.close()
    classify_all()
    assert _stage_of(db, "ovh1")[0] == "_tracker_overhead_"
