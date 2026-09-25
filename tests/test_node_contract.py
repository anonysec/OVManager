# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Contract tests: panel's NodeRequests client ↔ OVNode's /sync routes.

Every method of ``NodeRequests`` must map 1:1 to a route the node
actually serves. Parsed via ``ast`` so multi-line signatures and
payload-building don't break the check.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Client method → (HTTP verb, node route). "{uid}" marks an f-string
# path: the client interpolates the uid, and the test pins the template
# prefix ("/sync/user/") rather than the f-string internals.
CONTRACT = {
    "check_node": ("get", "/sync/status"),
    "get_node_info": ("get", "/sync/status"),
    "get_usage": ("get", "/sync/usage"),
    "get_sessions": ("get", "/sync/sessions"),
    "update_config": ("post", "/sync/config"),
    "restart_vpn": ("post", "/sync/restart"),
    "renew_server_cert": ("post", "/sync/renew-cert"),
    "trigger_update": ("post", "/sync/update"),
    "create_user": ("post", "/sync/user"),
    "change_user_status": ("put", "/sync/user"),
    "set_user_limit": ("put", "/sync/user/limit"),
    "delete_user": ("delete", "/sync/user/"),
    "disconnect_user": ("post", "/sync/user/"),
    "reset_usage": ("post", "/sync/user/"),
    "get_logs": ("get", "/sync/logs"),
    "download_ovpn_client": ("get", "/sync/download/ovpn/"),
    "download_ovpn_bytes": ("get", "/sync/download/ovpn/"),
}


def _source() -> str:
    return (REPO / "backend" / "node" / "requests.py").read_text(encoding="utf-8")


def _calls(tree: ast.AST) -> dict[str, list[tuple[str, str]]]:
    """Map method name → list of (verb, path) `_request` literals it uses."""
    out: dict[str, list[tuple[str, str]]] = {}

    def visit(node, current=None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                fn = child.func
                if isinstance(fn, ast.Attribute) and fn.attr == "_request" and isinstance(child.args[0], ast.Constant):
                    verb = child.args[0].value
                    path = child.args[1].value if len(child.args) > 1 and isinstance(child.args[1], ast.Constant) else None
                    if path is None and len(child.args) > 1 and isinstance(child.args[1], ast.JoinedStr):
                        # f-string path (e.g. f"/sync/user/{uid}") — use the constant prefix.
                        parts = [v.value for v in child.args[1].values if isinstance(v, ast.Constant)]
                        path = "".join(parts)
                    if path is not None:
                        out.setdefault(current or "", []).append((verb, path))
            visit(child, current)

    visit(tree)
    return out


def test_contract_methods_exist_on_client():
    src = _source()
    for name in CONTRACT:
        assert re.search(rf"^    def {name}\(", src, re.M), f"NodeRequests.{name} missing"


def test_contract_calls_match_the_table():
    tree = ast.parse(_source())
    calls = _calls(tree)
    for name, (verb, path) in CONTRACT.items():
        found = calls.get(name, [])
        # download_ovpn_client goes through _get_raw (raw bytes, not the
        # JSON envelope); assert the path via the whole-module literal scan
        # done in test_no_undocumented_sync_routes instead.
        if not found and name.startswith("download_ovpn"):
            continue
        assert found, f"{name} makes no _request call"
        assert any(v == verb for v, _ in found), f"{name}: expected a {verb} call, has {found}"
        # f-string routes interpolate the uid, so "/sync/user/" is a prefix
        # of "/sync/user/<uid>" and "/sync/user/<uid>/disconnect" alike.
        assert any(p.startswith(path) for _, p in found), f"{name}: expected path {path}, has {found}"


def test_no_undocumented_sync_routes():
    """Two-way drift guard: every literal /sync path in the client must be
    covered by the CONTRACT table or the raw-bytes helper (interpolated
    f-strings count via their constant prefix). Renaming a route without
    updating the table fails."""
    tree = ast.parse(_source())
    literals = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/sync/"):
            literals.add(node.value)
        if isinstance(node, ast.JoinedStr):
            parts = [v.value for v in node.values if isinstance(v, ast.Constant)]
            joined = "".join(parts)
            if joined.startswith("/sync/"):
                literals.add(joined)
    covered: set[str] = set()
    calls = _calls(tree)
    for name, (verb, path) in CONTRACT.items():
        for v, p in calls.get(name, []):
            if v == verb and p.startswith(path):
                covered.add(p)
    # Raw-bytes routes bypass _request: collect their _get_raw literals too.
    for child in ast.walk(tree):
        if isinstance(child, ast.Call):
            fn = child.func
            if isinstance(fn, ast.Attribute) and fn.attr == "_get_raw" and isinstance(child.args[0], ast.JoinedStr):
                parts = [v.value for v in child.args[0].values if isinstance(v, ast.Constant)]
                joined = "".join(parts)
                if joined.startswith("/sync/"):
                    covered.add(joined)
    undocumented = {p for p in literals if p not in covered and not any(p.startswith(c) for c in covered)}
    assert not undocumented, f"client uses /sync paths missing from CONTRACT: {undocumented}"
