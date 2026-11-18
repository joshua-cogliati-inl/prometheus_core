# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Tests for finding the unpublished generated Nexus client (no network).

Delete this file together with the lookup block in ``storage_client/__init__.py`` once the
package is published and listed as a dependency.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from prometheus_api import storage_client
from prometheus_api.storage_client import PATH_ENV_VAR, _import_nexus_package

PACKAGE = "deeplynx_nexus_client"


@pytest.fixture
def no_client_installed(monkeypatch):
    """Make ``import deeplynx_nexus_client`` fail unless a test puts a fake on sys.path.

    ``sys.modules`` entries for the package are saved and restored by hand: whatever a test
    imports under that name (a fake checkout) must not leak into later tests.
    """
    saved = {
        m: sys.modules.pop(m)
        for m in list(sys.modules)
        if m == PACKAGE or m.startswith(f"{PACKAGE}.")
    }
    saved_path = list(sys.path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not _has_package(p)])
    real_import = importlib.import_module

    def fake(name, *args, **kwargs):
        if name == PACKAGE and not any(_has_package(p) for p in sys.path):
            raise ImportError(f"No module named '{PACKAGE}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(storage_client.importlib, "import_module", fake)
    yield
    for name in [m for m in sys.modules if m == PACKAGE or m.startswith(f"{PACKAGE}.")]:
        del sys.modules[name]
    sys.modules.update(saved)
    sys.path[:] = saved_path


def _has_package(path: str) -> bool:
    return bool(path) and (Path(path) / PACKAGE).is_dir()


def test_missing_client_without_variable_names_both_ways_to_get_it(
    no_client_installed, monkeypatch
):
    """Covers REQ-001-13: the error tells the user how to install or locate the client."""
    monkeypatch.delenv(PATH_ENV_VAR, raising=False)

    with pytest.raises(ImportError) as caught:
        _import_nexus_package()

    assert PATH_ENV_VAR in str(caught.value)
    assert "pip install" in str(caught.value)


def test_variable_pointing_at_a_directory_without_the_package_is_rejected(
    no_client_installed, monkeypatch, tmp_path
):
    """Covers REQ-001-13: a wrong checkout path is reported with the variable's value."""
    monkeypatch.setenv(PATH_ENV_VAR, str(tmp_path))

    with pytest.raises(ImportError) as caught:
        _import_nexus_package()

    assert str(tmp_path) in str(caught.value)
    assert str(tmp_path) not in sys.path


def test_variable_pointing_at_a_checkout_makes_the_package_importable(
    no_client_installed, monkeypatch, tmp_path
):
    """Covers REQ-001-13: the checkout named by the variable is added to the import path."""
    package_dir = tmp_path / PACKAGE
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("MARK = 'from-checkout'\n")
    monkeypatch.setenv(PATH_ENV_VAR, str(tmp_path))

    _import_nexus_package()

    assert sys.modules[PACKAGE].MARK == "from-checkout"
    assert str(tmp_path) in sys.path
