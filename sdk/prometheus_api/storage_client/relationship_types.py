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

"""Helpers for relationship types (named relationships) shared by the sync and async resources.

An edge refers to its type by ``relationship_id`` or ``relationship_name``. The server resolves a
name case-insensitively among the organization's relationships and fails with a 500 when none
matches. The bulk edge route does not resolve names at all, only IDs. Several relationships may
share a name (the server does not prevent it), so name lookups pick the lowest ID.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .exceptions import StorageClientError, ValidationError
from .models.item import value_of


def is_missing_type_error(error: StorageClientError, name: str) -> bool:
    """True if ``error`` is the server's "relationship name not found" failure for ``name``."""
    text = str(error).lower()
    return f"relationship with name '{name.lower()}' not found" in text


def type_ids_by_name(relationships: Iterable[Any]) -> Dict[str, int]:
    """Map lower-cased relationship name to the lowest ID carrying that name."""
    ids: Dict[str, int] = {}
    for relationship in relationships:
        name = value_of(relationship, "name")
        relationship_id = value_of(relationship, "id")
        if not name or relationship_id is None:
            continue
        key = str(name).lower()
        ids[key] = min(int(relationship_id), ids.get(key, int(relationship_id)))
    return ids


def distinct_type_names(names: Iterable[str]) -> List[str]:
    """Non-empty names, one per case-insensitive spelling, in first-seen order."""
    seen: Dict[str, str] = {}
    for name in names:
        if name and name.lower() not in seen:
            seen[name.lower()] = name
    return list(seen.values())


def missing_type_error(names: Iterable[str]) -> ValidationError:
    """The error raised when types do not exist and may not be created automatically."""
    listed = ", ".join(f"'{name}'" for name in names)
    return ValidationError(
        f"Relationship type(s) {listed} do not exist in the organization. Create them first, "
        "or pass create_type_if_missing=True.",
        details={"missing_relationship_types": list(names)},
    )
