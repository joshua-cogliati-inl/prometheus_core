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

"""Storage Client Library - A generic abstraction for storage backend operations."""

# BEGIN unpublished-package lookup. The generated Nexus client is not on a package index yet.
# Delete this block (and its test, tests/test_nexus_package_lookup.py) once it is published and
# listed in pyproject.toml; a plain ``import deeplynx_nexus_client`` then does the job.
import importlib
import os
import sys
from pathlib import Path

_NEXUS_PACKAGE = "deeplynx_nexus_client"
PATH_ENV_VAR = "NEXUS_PYTHON_CLIENT_PATH"


def _import_nexus_package() -> None:
    """Import the generated client, or add ``$NEXUS_PYTHON_CLIENT_PATH`` to the path and retry."""
    try:
        importlib.import_module(_NEXUS_PACKAGE)
        return
    except ImportError as first_error:
        raw = os.environ.get(PATH_ENV_VAR, "").strip()
        hint = (
            f"The generated Nexus client ('{_NEXUS_PACKAGE}') is required but not installed. "
            f"Install it with 'pip install .' from the generated package, or set {PATH_ENV_VAR} "
            f"to a checkout that contains it."
        )
        if not raw:
            raise ImportError(f"{hint} (Import failed: {first_error})") from first_error
        path = Path(raw).expanduser()
        if not (path / _NEXUS_PACKAGE).is_dir():
            raise ImportError(
                f"{PATH_ENV_VAR}={raw} does not contain a '{_NEXUS_PACKAGE}' directory. {hint}"
            ) from first_error
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        try:
            importlib.import_module(_NEXUS_PACKAGE)
        except ImportError as error:
            raise ImportError(
                f"Found '{_NEXUS_PACKAGE}' under {PATH_ENV_VAR}={raw} but it failed to import "
                f"(its dependencies, such as attrs and python-dateutil, may be missing): {error}"
            ) from error


_import_nexus_package()
# END unpublished-package lookup


from .client import StorageClient  # noqa: E402
from .async_client import AsyncStorageClient  # noqa: E402
from .connection import ConnectionConfig  # noqa: E402
from .models.item import Item, ItemCreate, ItemUpdate, Tag  # noqa: E402
from .models.file import FileMetadata, FileUpload  # noqa: E402
from .models.relationship import Relationship, RelationshipCreate  # noqa: E402
from .models.pagination import Page, PageInfo  # noqa: E402
from .exceptions import (  # noqa: E402
    StorageClientError,
    AuthenticationError,
    ItemNotFoundError,
    ValidationError,
    APIError,
)

from prometheus_api import __version__  # noqa: E402

__all__ = [
    # Clients
    "StorageClient",
    "AsyncStorageClient",
    "__version__",
    # Configuration
    "ConnectionConfig",
    # Models
    "Item",
    "ItemCreate",
    "ItemUpdate",
    "Tag",
    "FileMetadata",
    "FileUpload",
    "Relationship",
    "RelationshipCreate",
    "Page",
    "PageInfo",
    # Exceptions
    "StorageClientError",
    "AuthenticationError",
    "ItemNotFoundError",
    "ValidationError",
    "APIError",
]
