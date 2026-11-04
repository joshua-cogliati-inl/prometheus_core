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

"""Sync tags resource."""

from typing import List

from ..models.tag import TagModel
from ..exceptions import StorageClientError
from ..nexus_client import generated_client, models, operation
from .base import BaseResource


class TagsResource(BaseResource):
    """Handles operations for project-level tags through the generated Nexus client."""

    def _generated(self):
        return generated_client(self._client)

    def list(self) -> List[TagModel]:
        """List all tags in the active project."""
        response = operation("project_tag", "api_get_all_tags_project").sync_detailed(
            self._client.config.project_id, client=self._generated()
        )
        if not isinstance(response.parsed, list):
            raise StorageClientError(
                f"Unexpected tag list response (HTTP {int(response.status_code)})"
            )
        return [TagModel.from_generated(t) for t in response.parsed]

    def create(self, name: str) -> TagModel:
        """Create a new tag in the active project."""
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("Tag name must be non-empty")

        generated = operation("project_tag", "api_create_a_tag_project")
        body = models().CreateTagRequestDto(name=normalized)
        response = generated.sync_detailed(
            self._client.config.project_id, client=self._generated(), body=body
        )
        if response.parsed is None or not hasattr(response.parsed, "name"):
            raise StorageClientError(
                f"Unexpected tag create response (HTTP {int(response.status_code)})"
            )
        return TagModel.from_generated(response.parsed)

    def get_or_create(self, name: str) -> TagModel:
        """Return the tag with the given name, creating it if it doesn't exist."""
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("Tag name must be non-empty")

        for tag in self.list():
            if tag.name == normalized:
                return tag
        return self.create(normalized)

    def resolve_ids(self, names: List[str]) -> List[int]:
        """Resolve a list of project tag names to positive integer IDs."""
        ids = []
        seen = set()
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            tag = self.get_or_create(name)
            if tag.id is None or int(tag.id) <= 0:
                raise ValueError(
                    f"DeepLynx project tag '{name}' did not return a valid positive id: "
                    f"{tag.model_dump()}"
                )
            ids.append(int(tag.id))
        return ids
