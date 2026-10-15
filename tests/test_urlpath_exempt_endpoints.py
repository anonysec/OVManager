"""With URLPATH set, the panel's real framework endpoints stay reachable — the rest does not.

The real URLPathMiddleware (mounted on an app shaped like ``backend.app.api``:
Swagger UI at ``/doc`` per ``app.py docs_url``, schema at ``/openapi.json``,
no default-FastAPI ``/docs``) with URLPATH monkeypatched on: exemption and
prefix rewrite run against genuine ASGI code, no DB write, no cache games.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.urlpath import URLPathMiddleware


def test_exempt_routes_pass_and_others_need_the_prefix(monkeypatch):
    import backend.urlpath._core as urlpath_mod

    monkeypatch.setattr(urlpath_mod, "get_urlpath", lambda: "hidden")

    # the panel's own shape, not FastAPI's defaults: app.py documents at /doc
    app = FastAPI(docs_url="/doc", openapi_url="/openapi.json")

    @app.get("/api/whoami")
    async def whoami():
        return {"ok": True}

    route_paths = {getattr(route, "path", None) for route in app.routes}
    # fixture uses FastAPI's default redoc_url="/redoc" — app.py passes no
    # redoc_url either, so the real table has /redoc whenever DOC=True
    assert {"/doc", "/redoc", "/openapi.json"} <= route_paths, route_paths
    assert "/docs" not in route_paths, "the panel serves Swagger UI at /doc, never /docs"

    client = TestClient(URLPathMiddleware(app))

    for path in ("/openapi.json", "/doc", "/redoc"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} must bypass URLPATH, got {resp.status_code}"

    hidden = client.get("/api/whoami")
    assert hidden.status_code == 404 and hidden.content == b"", "unprefixed non-exempt route must be swallowed"

    prefixed = client.get("/hidden/api/whoami")
    assert prefixed.status_code == 200 and prefixed.json() == {"ok": True}, "the prefix must rewrite into the app"
