def test_login_buckets_bounded(monkeypatch):
    import backend.auth.auth as a

    monkeypatch.setattr(a, "_login_attempts", {})
    monkeypatch.setattr(a, "_CLEANUP_INTERVAL", 10**9)
    for i in range(11000):
        a._put_bucket(f"k{i}", [0.0])
        if hasattr(a, "_enforce_bucket_cap"):
            a._enforce_bucket_cap()
    assert len(a._login_attempts) <= 10000


def test_sub_buckets_bounded(monkeypatch):
    import backend.routers.sub as s

    monkeypatch.setattr(s, "_SUB_ATTEMPTS", {})
    monkeypatch.setattr(s, "_sub_last_cleanup", 0.0)
    now = 1000.0
    for i in range(11000):
        s._SUB_ATTEMPTS[f"k{i}"] = [now]
    s._sub_purge_stale(now + 0.1)
    assert len(s._SUB_ATTEMPTS) <= 10000
