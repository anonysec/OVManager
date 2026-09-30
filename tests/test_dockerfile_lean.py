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
    assert "useradd -m -u 1000 -G ovpanel appuser" in runtime
    # ovpanel is what lets the panel read the .env bind-mounted at /app/.env;
    # compose cannot pass it through env_file because it would expand $NAME
    # inside the value and truncate the bcrypt hash.
    assert "groupadd -g 997 ovpanel" in runtime
    assert "/app/data" in runtime
    assert "HEALTHCHECK" in runtime


def test_runtime_image_ships_the_operator_cli():
    """`ovm` runs cli.main inside the container — the image has to carry it.

    Every command manager.sh delegates (`status`, `doctor`, backups, and now
    `reset-password`) is `docker exec ovmanager /app/.venv/bin/python -m
    cli.main`. Without this COPY that exec dies with ModuleNotFoundError, and
    on a docker install the owner credential could never be changed.
    """
    runtime = _stages()[-1]
    assert "COPY cli/ ./cli/" in runtime, "the runtime stage must ship cli/"
    assert "COPY backend/ ./backend/" in runtime, "and the package the CLI imports"


def test_runtime_image_ships_no_pip():
    """pip was the only thing Trivy ever flagged in this image.

    Six findings, all in the base image's pip 25.0.1, all MEDIUM/LOW. Nothing
    at runtime installs anything — the venv is resolved in the builder stage —
    so pip is removed rather than left to rot into CVEs.
    """
    runtime = _stages()[-1]
    assert "pip uninstall" in runtime, "pip must be removed from the runtime image"
    assert "pip install" not in runtime, "nothing may install packages at runtime"
    # The lean test already forbids pip install; make sure the removal is real
    # by requiring the verification step too, not just the uninstall.
    assert "importlib.metadata" in runtime
