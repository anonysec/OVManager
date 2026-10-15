"""With URLPATH set, the framework endpoints stay reachable — the rest does not.

The real URLPathMiddleware (mounted on a default FastAPI, which owns the
/docs /redoc /openapi.json routes) with URLPATH monkeypatched on: exemption
and prefix rewrite run against genuine ASGI code, no DB write, no cache games.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.urlpath import URLPathMiddleware


def test_exempt_routes_pass_and_others_need_the_prefix(monkeypatch):
    import backend.urlpath._core as urlpath_mod

    monkeypatch.setattr(urlpath_mod, "get_urlpath", lambda: "hidden")

    app = FastAPI()

    @app.get("/api/whoami")
    async def whoami():
        return {"ok": True}

    client = TestClient(URLPathMiddleware(app))

    for path in ("/openapi.json", "/docs", "/redoc"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} must bypass URLPATH, got {resp.status_code}"

    hidden = client.get("/api/whoami")
    assert hidden.status_code == 404 and hidden.content == b"", "unprefixed non-exempt route must be swallowed"

    prefixed = client.get("/hidden/api/whoami")
    assert prefixed.status_code == 200 and prefixed.json() == {"ok": True}, "the prefix must rewrite into the app"
