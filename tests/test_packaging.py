"""The pip/pipx package must ship every Python package in the repo."""
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")    # Python 3.11+

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_lists_every_package():
    # Listing py-modules turns off setuptools' package discovery; a package missing
    # here is missing from the wheel, and a pipx install crashes on start.
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = set(cfg["tool"]["setuptools"]["packages"])
    on_disk = {".".join(p.parent.relative_to(ROOT).parts)
               for p in (ROOT / "tsconverter").rglob("__init__.py")}
    assert on_disk <= listed, f"add to pyproject.toml packages: {sorted(on_disk - listed)}"
