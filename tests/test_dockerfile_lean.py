# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Structural guards for the panel image (no Docker daemon in the test env).

The runtime stage must stay lean: deps are resolved once in a builder stage,
and the runtime copies that venv and starts it directly — no uv, no compiler.
These assertions catch an accidental return to ``pip install uv`` / ``uv run``
in the final image without needing a docker build.
"""

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _stages() -> list[str]:
    """Split the Dockerfile into one blob per FROM stage."""
    stages: list[list[str]] = []
    for line in _text().splitlines():
        if line.upper().startswith("FROM "):
            stages.append([])
        if stages:
            stages[-1].append(line)
    return ["\n".join(stage) for stage in stages]


def test_builder_resolves_locked_deps():
    stages = _stages()
    assert len(stages) >= 3, "frontend + builder + runtime stages expected"
    assert any("uv sync --frozen" in stage for stage in stages), "a builder stage must run uv sync --frozen"


def test_runtime_stage_has_no_uv_or_pip_install():
    runtime = _stages()[-1].lower()
    assert "pip install" not in runtime
    assert "uv sync" not in runtime
    assert "uv run" not in runtime


def test_runtime_starts_venv_python_directly():
    assert 'CMD ["/app/.venv/bin/python", "main.py"]' in _text()


def test_runtime_user_data_dir_and_healthcheck_kept():
    runtime = _stages()[-1]
    assert "USER appuser" in runtime
    assert "useradd -m -u 1000 appuser" in runtime
    assert "/app/data" in runtime
    assert "HEALTHCHECK" in runtime
