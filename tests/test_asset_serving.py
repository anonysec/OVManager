"""Asset serving: immutable caching + precompressed .gz fast path."""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from backend.app import AssetCacheMiddleware, api, frontend_build_path

client = TestClient(api)

requires_build = pytest.mark.skipif(
    not os.path.isdir(os.path.join(frontend_build_path, "assets")),
    reason="frontend not built",
)


def _js_asset():
    assets = os.path.join(frontend_build_path, "assets")
    return next(f for f in os.listdir(assets) if f.endswith(".js"))


@requires_build
def test_assets_are_immutable_cached():
    r = client.get(f"/assets/{_js_asset()}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


@requires_build
def test_assets_serve_precompressed_gzip():
    assets = os.path.join(frontend_build_path, "assets")
    name = _js_asset()
    assert os.path.isfile(os.path.join(assets, name + ".gz")), "build must emit .gz siblings"
    gzipr = client.get(f"/assets/{name}", headers={"Accept-Encoding": "gzip"})
    assert gzipr.status_code == 200
    assert gzipr.headers["content-encoding"] == "gzip"
    assert gzipr.headers["vary"] == "Accept-Encoding"
    plain = client.get(f"/assets/{name}", headers={"Accept-Encoding": "identity"})
    assert gzipr.content == plain.content


def test_path_traversal_is_not_served_by_the_asset_middleware():
    """A '..' path must not be answered by the .gz fast path — it goes to the
    normal stack (which refuses or 404s it)."""
    responses = []

    async def downstream(scope, receive, send):
        responses.append(scope)

    mw = AssetCacheMiddleware(downstream, frontend_build_path)
    scope = {"type": "http", "method": "GET", "path": "/assets/../../../etc/passwd", "headers": []}
    asyncio.run(mw(scope, None, None))
    assert len(responses) == 1  # passed through untouched, no fast-path body


def test_non_asset_paths_untouched():
    responses = []

    async def downstream(scope, receive, send):
        responses.append(scope)

    mw = AssetCacheMiddleware(downstream, frontend_build_path)
    scope = {"type": "http", "method": "GET", "path": "/api/users/", "headers": []}
    asyncio.run(mw(scope, None, None))
    assert len(responses) == 1
