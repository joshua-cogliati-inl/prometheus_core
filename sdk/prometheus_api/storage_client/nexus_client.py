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

"""Locate and drive the generated Nexus Python client (``deeplynx_nexus_client``).

The generated client is not published to an index yet, so it is found either on the normal
import path (``pip install .`` from the generated package) or in the checkout named by the
``NEXUS_PYTHON_CLIENT_PATH`` environment variable.

Generated operations call ``client.get_httpx_client().request(...)`` and
``client.get_async_httpx_client().request(...)``. The httpx clients built here route those
calls through the storage client's own ``_request``, so authentication, token refresh,
retries and the mapping of HTTP errors to storage exceptions stay in one place. Because
``_request`` raises on non-2xx statuses, generated operations only ever parse successes.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import httpx

from .exceptions import StorageClientError

if TYPE_CHECKING:
    from .async_client import AsyncStorageClient
    from .client import StorageClient

PATH_ENV_VAR = "NEXUS_PYTHON_CLIENT_PATH"
PACKAGE = "deeplynx_nexus_client"


def ensure_nexus_client() -> ModuleType:
    """Import and return the generated client package, or raise a message saying how to get it."""
    try:
        return importlib.import_module(PACKAGE)
    except ImportError as first_error:
        raw = os.environ.get(PATH_ENV_VAR, "").strip()
        if not raw:
            raise StorageClientError(
                f"The generated Nexus client ('{PACKAGE}') is not installed. Install it with "
                f"'pip install .' from the generated package, or set {PATH_ENV_VAR} to a "
                f"checkout that contains it. (Import failed: {first_error})"
            ) from first_error
        path = Path(raw).expanduser()
        if not (path / PACKAGE).is_dir():
            raise StorageClientError(
                f"{PATH_ENV_VAR}={raw} does not contain a '{PACKAGE}' directory."
            ) from first_error
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        try:
            return importlib.import_module(PACKAGE)
        except ImportError as error:
            raise StorageClientError(
                f"Found '{PACKAGE}' under {PATH_ENV_VAR}={raw} but it failed to import "
                f"(its dependencies, e.g. attrs and python-dateutil, may be missing): {error}"
            ) from error


def models() -> ModuleType:
    """Return the generated ``models`` subpackage (importing it, as the package does not)."""
    ensure_nexus_client()
    return importlib.import_module(f"{PACKAGE}.models")


def types() -> ModuleType:
    """Return the generated ``types`` module (``File`` and friends)."""
    ensure_nexus_client()
    return importlib.import_module(f"{PACKAGE}.types")


def operation(group: str, name: str) -> ModuleType:
    """Return the generated operation module ``api/<group>/<name>``."""
    ensure_nexus_client()
    return importlib.import_module(f"{PACKAGE}.api.{group}.{name}")


class _RoutedClient(httpx.Client):
    """An httpx client whose requests are sent by ``StorageClient._request``."""

    def __init__(self, owner: "StorageClient"):
        super().__init__()
        self._owner = owner

    def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        return self._owner._request(str(method).upper(), str(url), **kwargs)


class _RoutedAsyncClient(httpx.AsyncClient):
    """An httpx async client whose requests are sent by ``AsyncStorageClient._request``."""

    def __init__(self, owner: "AsyncStorageClient"):
        super().__init__()
        self._owner = owner

    async def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        return await self._owner._request(str(method).upper(), str(url), **kwargs)


def generated_client(owner: Any, *, asynchronous: bool = False) -> Any:
    """Return a generated ``Client`` whose requests go through ``owner._request``.

    The result is cached on ``owner`` (one per sync or async owner).
    """
    cached = getattr(owner, "_generated_client", None)
    if cached is not None:
        return cached
    package = ensure_nexus_client()
    client = package.Client(base_url=owner.config.base_url)
    if asynchronous:
        client.set_async_httpx_client(_RoutedAsyncClient(owner))
    else:
        client.set_httpx_client(_RoutedClient(owner))
    owner._generated_client = client
    return client
