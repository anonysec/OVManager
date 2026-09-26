"""Tests for transition-based node-down Telegram alerts."""

from __future__ import annotations

import pytest

from backend.operations import node_alerts


def _row(node_id: int, name: str, reachable: bool) -> dict:
    return {"node_id": node_id, "node_name": name, "reachable": 1 if reachable else 0}


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Fresh in-memory state + captured send_telegram calls for every test."""
    node_alerts._node_state.clear()
    node_alerts._last_down_alert.clear()
    node_alerts._alerted_down.clear()
    calls: list[str] = []

    def fake_send(text, db=None):
        calls.append(text)
        return True

    monkeypatch.setattr(node_alerts, "send_telegram", fake_send)
    yield calls
    node_alerts._node_state.clear()
    node_alerts._last_down_alert.clear()
    node_alerts._alerted_down.clear()


T0 = 1_000_000.0


def test_first_tick_seeds_state_without_alerting(_clean_state):
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0) == 0
    assert _clean_state == []
    assert node_alerts._node_state == {1: False}


def test_down_transition_alerts_once(_clean_state):
    assert node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0) == 0
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 300) == 1
    assert _clean_state == ["🔴 Node de-1 is unreachable."]
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 600) == 0
    assert len(_clean_state) == 1


def test_recovery_alerts_after_announced_outage(_clean_state):
    node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0)
    node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 300)
    assert node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0 + 900) == 1
    assert _clean_state[-1] == "🟢 Node de-1 is back online."
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 2400) == 1
    assert node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0 + 2700) == 1
    assert len(_clean_state) == 4


def test_flapping_within_cooldown_is_suppressed(_clean_state):
    node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0)
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 300) == 1
    assert node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0 + 600) == 1  # recovery
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 900) == 0
    assert len(_clean_state) == 2
    assert node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0 + 1200) == 0
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 2100) == 1
    assert len(_clean_state) == 3


def test_failed_send_is_retried_next_tick(_clean_state, monkeypatch):
    node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0)
    flaky: list[bool] = [False, True]

    def flaky_send(text, db=None):
        return flaky.pop(0)

    monkeypatch.setattr(node_alerts, "send_telegram", flaky_send)
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 300) == 0
    assert node_alerts._alerted_down == set()
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 600) == 1
    assert 1 in node_alerts._alerted_down


def test_notify_off_updates_state_silently(_clean_state):
    assert node_alerts.check_node_alerts([_row(1, "de-1", True)], now=T0, notify=False) == 0
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 300, notify=False) == 0
    assert node_alerts._node_state == {1: False}
    assert node_alerts._alerted_down == set()
    assert node_alerts.check_node_alerts([_row(1, "de-1", False)], now=T0 + 600) == 1


def test_multiple_nodes_are_independent(_clean_state):
    node_alerts.check_node_alerts([_row(1, "de-1", True), _row(2, "nl-1", True)], now=T0)
    assert node_alerts.check_node_alerts([_row(1, "de-1", False), _row(2, "nl-1", True)], now=T0 + 300) == 1
    assert _clean_state == ["🔴 Node de-1 is unreachable."]
    assert node_alerts.check_node_alerts([_row(1, "de-1", False), _row(2, "nl-1", False)], now=T0 + 600) == 1
    assert _clean_state[-1] == "🔴 Node nl-1 is unreachable."
