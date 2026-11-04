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

"""Tests for locating and driving the generated Nexus client (no network)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from prometheus_api.storage_client import nexus_client
from prometheus_api.storage_client.exceptions import StorageClientError
from prometheus_api.storage_client.nexus_client import (
    PACKAGE,
    PATH_ENV_VAR,
    ensure_nexus_client,
    generated_client,
    operation,
)


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
    monkeypatch.setattr(
        nexus_client.importlib,
        "import_module",
        _blocking_import(nexus_client.importlib.import_module),
    )
    yield
    for name in [m for m in sys.modules if m == PACKAGE or m.startswith(f"{PACKAGE}.")]:
        del sys.modules[name]
    sys.modules.update(saved)
    sys.path[:] = saved_path


def _blocking_import(real_import):
    def fake(name, *args, **kwargs):
        if name == PACKAGE and not _fake_on_path():
            raise ImportError(f"No module named '{PACKAGE}'")
        return real_import(name, *args, **kwargs)

    return fake


def _has_package(path: str) -> bool:
    return bool(path) and (Path(path) / PACKAGE).is_dir()


def _fake_on_path() -> bool:
    return any(_has_package(p) for p in sys.path)


def test_missing_client_without_variable_names_both_ways_to_get_it(
    no_client_installed, monkeypatch
):
    """Covers REQ-001-13: the error tells the user how to install or locate the client."""
    monkeypatch.delenv(PATH_ENV_VAR, raising=False)

    with pytest.raises(StorageClientError) as caught:
        ensure_nexus_client()

    assert PATH_ENV_VAR in str(caught.value)
    assert "pip install" in str(caught.value)


def test_variable_pointing_at_a_directory_without_the_package_is_rejected(
    no_client_installed, monkeypatch, tmp_path
):
    """Covers REQ-001-13: a wrong checkout path is reported with the variable's value."""
    monkeypatch.setenv(PATH_ENV_VAR, str(tmp_path))

    with pytest.raises(StorageClientError) as caught:
        ensure_nexus_client()

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

    module = ensure_nexus_client()

    assert module.MARK == "from-checkout"


class RecordingOwner:
    def __init__(self):
        self.config = SimpleNamespace(base_url="http://nexus.test/api/v1")
        self.calls = []

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return httpx.Response(200, json=[{"id": 3, "name": "a"}])


class AsyncRecordingOwner(RecordingOwner):
    async def _request(self, method, path, **kwargs):
        return super()._request(method, path, **kwargs)


def _real_client_or_skip():
    try:
        ensure_nexus_client()
    except StorageClientError:
        pytest.skip(f"{PACKAGE} is not installed and {PATH_ENV_VAR} is not set")


def test_generated_operation_is_sent_through_the_owners_request():
    """Covers REQ-001-13: generated calls reach ``_request`` so auth and errors stay in one place."""
    _real_client_or_skip()
    owner = RecordingOwner()

    result = operation("project_tag", "api_get_all_tags_project").sync_detailed(
        5, client=generated_client(owner)
    )

    assert owner.calls[0][0] == "GET"
    assert owner.calls[0][1] == "/projects/5/tags"
    assert result.parsed[0].name == "a"
    assert generated_client(owner) is generated_client(owner)


async def test_generated_async_operation_is_sent_through_the_owners_request():
    """Covers REQ-001-13: the async variant is routed through the async ``_request``."""
    _real_client_or_skip()
    owner = AsyncRecordingOwner()

    result = await operation("project_tag", "api_get_all_tags_project").asyncio_detailed(
        5, client=generated_client(owner, asynchronous=True)
    )

    assert owner.calls[0][:2] == ("GET", "/projects/5/tags")
    assert result.parsed[0].id == 3


@pytest.mark.requires_nexus_client
def test_models_accessor_works_in_a_fresh_interpreter():
    """Covers REQ-001-13: ``models()`` must not rely on an operation having imported the models.

    The generated package does not import its ``models`` subpackage itself; inside this test
    process some other test usually has, so the check needs a clean interpreter.
    """
    import subprocess

    code = (
        "from prometheus_api.storage_client.nexus_client import models;"
        "print(models().RecordResponseDto.__name__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "RecordResponseDto"
