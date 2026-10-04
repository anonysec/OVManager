"""Every path through the asset cache must stay inside the assets directory.

Three distinct escapes, all unauthenticated, all returning 200 with the file's
contents. The payloads are chosen so each one SUCCEEDS against the code that
predates the fix — a test using a `..` payload only proves the old `..` guard
works, which is why the suite stayed green against vulnerable code.
"""

import gzip

import pytest

from backend.middlewares import AssetCacheMiddleware


async def _fetch(mw, path, gzip_ok=True):
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request"}

    headers = [(b"accept-encoding", b"gzip")] if gzip_ok else []
    await mw({"type": "http", "method": "GET", "path": path, "headers": headers}, receive, send)
    start = next((m for m in sent if m.get("type") == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in sent if m.get("type") == "http.response.body")
    return (start or {}).get("status"), body


def _notfound(scope, receive, send):
    async def inner():
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return inner()


@pytest.fixture
def tree(tmp_path):
    """assets/ holds one real file; a secret lives outside the tree."""
    front = tmp_path / "frontend"
    assets = front / "assets"
    assets.mkdir(parents=True)
    secret = tmp_path / "secret.json"
    secret.write_text('{"owner":"admin","hash":"LEAKED"}')
    (assets / "app.js").write_text("console.log(1)")
    with gzip.open(str(tmp_path) + "/secret.json.gz", "wb") as f:
        f.write(b'{"owner":"admin","hash":"LEAKED"}')
    # a legitimate sibling, so the happy path stays covered
    with gzip.open(str(assets / "app.js.gz"), "wb") as f:
        f.write(b"console.log(1)")
    return front, assets, secret


@pytest.mark.asyncio
async def test_absolute_rel_escapes_base(tree):
    """GET /assets//etc/passwd — the leading slash makes os.path.join discard base."""
    front, assets, secret = tree
    status, body = await _fetch(AssetCacheMiddleware(_notfound, str(front)), f"/assets//{str(secret).lstrip('/')}")
    assert status == 404, f"leaked with {status}"
    assert b"LEAKED" not in body


@pytest.mark.asyncio
async def test_dotdot_escapes_base(tree):
    front, assets, secret = tree
    status, body = await _fetch(AssetCacheMiddleware(_notfound, str(front)), "/assets/../../secret.json")
    assert status == 404
    assert b"LEAKED" not in body


@pytest.mark.asyncio
async def test_gz_sibling_symlink_escapes_base(tree):
    """The gzip path opens cand + '.gz', so THAT file is what must be confined.

    A symlink planted inside assets/ pointing out of the tree was served with
    200 and the file's contents: the fix checked `cand` and never the sibling
    that actually gets read.
    """
    front, assets, secret = tree
    link = assets / "sneaky.js.gz"
    link.symlink_to(str(secret) + ".gz")
    (assets / "sneaky.js").write_text("x")
    status, body = await _fetch(AssetCacheMiddleware(_notfound, str(front)), "/assets/sneaky.js")
    assert status == 404, f"gz symlink leaked with {status}"
    assert b"LEAKED" not in (gzip.decompress(body) if body else b"")


@pytest.mark.asyncio
async def test_a_real_asset_is_still_served(tree):
    """The confinement must not break the fast path it was added to protect."""
    front, assets, secret = tree
    status, body = await _fetch(AssetCacheMiddleware(_notfound, str(front)), "/assets/app.js")
    assert status == 200, "a legitimate hashed asset stopped being served"
    assert gzip.decompress(body) == b"console.log(1)"
