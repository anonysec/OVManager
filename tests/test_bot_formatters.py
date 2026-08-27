# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from datetime import date, timedelta

from bot.formatters import (
    esc,
    expiry_label,
    fmt_bytes,
    fmt_uptime,
    is_expired,
    plan_label,
    status_label,
    usage_line,
    user_card,
)


def test_fmt_bytes_unlimited_and_scale():
    assert fmt_bytes(None) == "Unlimited"
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(1073741824) == "1.0 GB"


def test_expiry_and_status():
    future = (date.today() + timedelta(days=12)).isoformat()
    past = (date.today() - timedelta(days=3)).isoformat()
    assert expiry_label(None) == "No expiry"
    assert expiry_label("2099-12-31") == "No expiry"
    assert "12 days left" in expiry_label(future)
    assert "Expired 3d ago" in expiry_label(past)
    assert status_label({"is_active": True, "expiry_date": future}) == "Active"
    assert status_label({"is_active": True, "online": True, "expiry_date": future}) == "Online"
    assert status_label({"is_active": False, "expiry_date": future}) == "Disabled"
    assert is_expired({"expiry_date": past})


def test_usage_and_card_escape():
    user = {
        "name": "ali<x>",
        "is_active": True,
        "used": 512,
        "total": 1024,
        "max_logins": 1,
        "active_connections": 0,
        "expiry_date": (date.today() + timedelta(days=5)).isoformat(),
        "owner": "root",
        "uuid": "abc",
    }
    assert "50%" in usage_line(user)
    card = user_card(user)
    assert "ali&lt;x&gt;" in card
    assert "<script>" not in card
    assert esc("<b>") == "&lt;b&gt;"


def test_plan_and_uptime():
    assert plan_label(30, 100, 1) == "30 days · 100 GB · 1 device"
    assert "No expiry" in plan_label(0, 0, 0)
    assert fmt_uptime(90) == "1m"
    assert "1d" in fmt_uptime(90000)
