from pathlib import Path


def test_makefile_checks_both_scripts():
    text = Path("Makefile").read_text()
    assert "bash -n install.sh && bash -n manager.sh" in text
    assert "scripts/lib/*.sh" not in text.split("lint-backend")[1].split("\n\n")[0]
