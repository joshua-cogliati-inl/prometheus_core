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

"""Relationships resource for synchronous operations."""

import json
from typing import Any, Dict, List, Optional
from ..models.item import value_of
from ..models.relationship import Relationship, RelationshipCreate
from ..relationship_types import (
    distinct_type_names,
    is_missing_type_error,
    missing_type_error,
    type_ids_by_name,
)
from ..exceptions import StorageClientError
from ..nexus_client import ensure_nexus_client, generated_client, operation
from .base import BaseResource


class RelationshipsResource(BaseResource):
    """Handles operations related to relationships between items."""

    def _generated(self) -> Any:
        return generated_client(self._client)

    def _scope(self) -> tuple:
        config = self._client.config
        return config.organization_id, config.project_id

    @staticmethod
    def _edge(response: Any, action: str) -> Relationship:
        """Build a relationship from a generated edge response.

        Some DeepLynx endpoints wrap the edge in ``{"value": ...}``; the generated parser does
        not see through that, so the wrapped body is re-parsed here.
        """
        parsed = response.parsed
        if parsed is not None and value_of(parsed, "origin_id") is None:
            try:
                body = json.loads(response.content)
            except ValueError:
                body = None
            if isinstance(body, dict) and isinstance(body.get("value"), dict):
                dto = ensure_nexus_client().models.EdgeResponseDto.from_dict(body["value"])
                return Relationship.from_generated(dto)
        if parsed is None or not hasattr(parsed, "id"):
            raise StorageClientError(
                f"Unexpected response to {action} (HTTP {int(response.status_code)})"
            )
        return Relationship.from_generated(parsed)

    def create(
        self, relationship: RelationshipCreate, create_type_if_missing: bool = True
    ) -> Relationship:
        """Create a new relationship between two items.

        The relationship type is sent by name. Nexus resolves the name among the organization's
        relationships and fails when there is none; with ``create_type_if_missing`` the type is
        then created at organization level and the request is retried once.

        Args:
            relationship: Relationship creation data
            create_type_if_missing: Create an unknown ``relationship_type`` instead of failing

        Returns:
            Created relationship. ``relationship_type`` echoes the requested type.

        Raises:
            ValidationError: If the type does not exist and ``create_type_if_missing`` is False

        Example:
            ```python
            rel = client.relationships.create(RelationshipCreate(
                from_item_id=1,
                to_item_id=2,
                relationship_type="depends_on",
                properties={"strength": "strong"}
            ))
            ```
        """
        name = (relationship.relationship_type or "").strip() or None
        try:
            return self._create_edge(relationship, name)
        except StorageClientError as error:
            if not name or not is_missing_type_error(error, name):
                raise
            if not create_type_if_missing:
                raise missing_type_error([name]) from error
        self._resolve_type_ids([name], create_missing=True)
        return self._create_edge(relationship, name)

    def _create_edge(self, relationship: RelationshipCreate, name: Optional[str]) -> Relationship:
        organization_id, project_id = self._scope()
        response = operation("edge", "api_create_an_edge").sync_detailed(
            organization_id,
            project_id,
            client=self._generated(),
            body=relationship.to_generated(relationship_name=name),
            data_source_id=self._client._get_data_source_id(),
        )
        edge = self._edge(response, "create relationship")
        if name and edge.relationship_pair_id is not None:
            return edge.model_copy(update={"relationship_type": name})
        return edge

    def _resolve_type_ids(self, names: List[str], create_missing: bool) -> Dict[str, int]:
        """IDs of the named relationship types (keys lower-cased), creating missing ones."""
        organization_id, _ = self._scope()
        listed = operation(
            "organization_relationship", "api_get_all_relationships_organization"
        ).sync_detailed(organization_id, client=self._generated())
        if not isinstance(listed.parsed, list):
            raise StorageClientError(
                f"Unexpected response to list relationship types (HTTP {int(listed.status_code)})"
            )
        ids = type_ids_by_name(listed.parsed)
        missing = [name for name in names if name.lower() not in ids]
        if missing and not create_missing:
            raise missing_type_error(missing)
        models = ensure_nexus_client().models
        for name in missing:
            created = operation(
                "organization_relationship", "api_create_a_relationship_organization"
            ).sync_detailed(
                organization_id,
                client=self._generated(),
                body=models.CreateRelationshipRequestDto(name=name),
            )
            if created.parsed is None or not hasattr(created.parsed, "id"):
                raise StorageClientError(
                    f"Unexpected response to create relationship type '{name}' "
                    f"(HTTP {int(created.status_code)})"
                )
            ids[name.lower()] = int(created.parsed.id)
        return ids

    def get(self, relationship_id: int) -> Relationship:
        """Get a relationship by ID.

        Raises:
            ItemNotFoundError: If relationship doesn't exist
        """
        organization_id, project_id = self._scope()
        response = operation("edge", "api_get_edge_by_id").sync_detailed(
            organization_id, project_id, relationship_id, client=self._generated()
        )
        return self._edge(response, "get relationship")

    def delete(self, relationship_id: int) -> None:
        """Delete a relationship.

        Raises:
            ItemNotFoundError: If relationship doesn't exist
        """
        organization_id, project_id = self._scope()
        operation("edge", "api_delete_edge_by_id").sync_detailed(
            organization_id, project_id, relationship_id, client=self._generated()
        )

    def bulk_create(
        self, relationships: List[RelationshipCreate], create_type_if_missing: bool = True
    ) -> List[Relationship]:
        """Create multiple relationships in a single request.

        The bulk route accepts relationship IDs, not names, so the distinct types are resolved
        first (one list request) and missing ones are created when ``create_type_if_missing``.

        Args:
            relationships: List of relationships to create
            create_type_if_missing: Create unknown ``relationship_type`` values instead of failing

        Returns:
            List of created relationships, with ``relationship_type`` echoing the requested type

        Raises:
            ValidationError: If a type does not exist and ``create_type_if_missing`` is False

        Example:
            ```python
            rels = client.relationships.bulk_create([
                RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="links"),
                RelationshipCreate(from_item_id=2, to_item_id=3, relationship_type="links")
            ])
            ```
        """
        names = distinct_type_names((r.relationship_type or "").strip() for r in relationships)
        ids = self._resolve_type_ids(names, create_type_if_missing) if names else {}
        organization_id, project_id = self._scope()
        response = operation("edge", "api_create_many_edges").sync_detailed(
            organization_id,
            project_id,
            client=self._generated(),
            body=[
                r.to_generated(relationship_id=ids.get((r.relationship_type or "").strip().lower()))
                for r in relationships
            ],
            data_source_id=self._client._get_data_source_id(),
        )
        if not isinstance(response.parsed, list):
            raise StorageClientError(
                f"Unexpected response to bulk create (HTTP {int(response.status_code)})"
            )
        names_by_id = {ids[name.lower()]: name for name in names}
        created = [Relationship.from_generated(edge) for edge in response.parsed]
        return [
            edge.model_copy(update={"relationship_type": names_by_id[edge.relationship_pair_id]})
            if edge.relationship_pair_id in names_by_id
            else edge
            for edge in created
        ]

    def get_item_relationships(
        self, item_id: int, direction: Optional[str] = None
    ) -> List[Relationship]:
        """Get all relationships for an item.

        Args:
            item_id: Item identifier
            direction: Filter by direction ('outgoing', 'incoming', or None for both)

        Returns:
            List of relationships. The list route returns only the related record and the
            relationship's name, so ``id`` is 0 and ``properties`` is empty.

        Example:
            ```python
            all_rels = client.relationships.get_item_relationships(123)
            outgoing = client.relationships.get_item_relationships(123, "outgoing")
            ```
        """
        # If direction not specified, get both outgoing and incoming
        if direction is None:
            outgoing = self.get_item_relationships(item_id, "outgoing")
            incoming = self.get_item_relationships(item_id, "incoming")
            return outgoing + incoming

        # outgoing: this item is the origin (isOrigin=true); incoming: it is the destination
        is_origin = direction == "outgoing"
        organization_id, project_id = self._scope()
        response = operation("record", "api_get_edges_by_record").sync_detailed(
            organization_id,
            project_id,
            item_id,
            client=self._generated(),
            is_origin=is_origin,
            page=1,
            page_size=100,  # Maximum allowed by DeepLynx API
        )
        if not isinstance(response.parsed, list):
            raise StorageClientError(
                f"Unexpected response to list relationships (HTTP {int(response.status_code)})"
            )
        return [
            Relationship.from_related_record(related, item_id, is_origin)
            for related in response.parsed
        ]

    def get_item_graph(self, item_id: int, depth: int = 1) -> Dict[str, Any]:
        """Get a graph of relationships starting from an item.

        Args:
            item_id: Starting item identifier
            depth: How many levels deep to traverse

        Returns:
            Graph structure with items and relationships

        Example:
            ```python
            graph = client.relationships.get_item_graph(123, depth=2)
            ```
        """
        response = self._client._request(
            "GET", f"{self._base_path}/records/{item_id}/graph", params={"depth": depth}
        )

        data = response.json()
        return data if isinstance(data, dict) else {"result": data}
