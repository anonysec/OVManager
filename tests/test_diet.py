"""Production diet: the server venv must stay lean.

Background: a 140 MB Playwright install once landed in a production venv.
These tests pin the hygiene rules so it cannot happen again:
- runtime code (backend/, bot/, main.py) imports only runtime deps + stdlib,
  never test/dev-only packages;
- every `uv sync` invocation that provisions a server (install.sh,
  Dockerfile) uses --frozen --no-dev.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BANNED_RUNTIME_IMPORTS = {
    "pytest",
    "playwright",
    "pygments",
    "cyclonedx",
    "pip_audit",
    "yaml",  # PyYAML: not a runtime dep; keep the tree PyYAML-free
}

RUNTIME_DIRS = [REPO / "backend", REPO / "bot", REPO / "main.py"]


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def test_runtime_code_has_no_dev_only_imports():
    offenders = []
    for base in RUNTIME_DIRS:
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in files:
            bad = _imports_of(path) & BANNED_RUNTIME_IMPORTS
            if bad:
                offenders.append(f"{path.relative_to(REPO)}: {sorted(bad)}")
    assert not offenders, offenders


def test_server_syncs_are_no_dev():
    """install.sh + Dockerfile provision servers — dev extras must not ship."""
    for rel, pattern in (
        ("install.sh", r'"\$UV_BIN" sync --[^\n]*--no-dev'),
        ("Dockerfile", r"uv sync --frozen --no-dev"),
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert re.search(pattern, text), f"{rel} must uv sync with --no-dev"


def test_venv_budget_documents_expectation():
    """Every project dependency must be imported somewhere in runtime code
    (no dead weight in the venv)."""
    import tomllib

    with open(REPO / "pyproject.toml", "rb") as f:
        declared = tomllib.load(f)["project"]["dependencies"]
    declared_mods = set()
    for dep in declared:
        name = re.split(r"[<>=!;\s\[]", dep, maxsplit=1)[0].replace("-", "_").lower()
        declared_mods.add(name)
    aliases = {
        "python_dotenv": {"dotenv"},
        "python_multipart": {"multipart"},
        "python_telegram_bot": {"telegram"},
        "pydantic_settings": {"pydantic_settings"},
        "uvicorn": {"uvicorn"},
    }
    framework_required = {"python_multipart", "jinja2", "python_dotenv"}
    used = set()
    for base in RUNTIME_DIRS:
        files = [base] if base.is_file() else list(base.rglob("*.py"))
        for path in files:
            used |= _imports_of(path)
    unused = set()
    for mod in declared_mods:
        if mod in framework_required:
            continue
        names = aliases.get(mod, {mod})
        if not (names & used):
            unused.add(mod)
    assert not unused, f"declared but never imported (dead venv weight): {sorted(unused)}"
