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
from deeplynx_nexus_client.api.edge import api_delete_edge_by_id
from deeplynx_nexus_client.api.edge import api_get_edge_by_id
from deeplynx_nexus_client.api.record import api_get_edges_by_record
from deeplynx_nexus_client.api.record import api_get_graph_data_for_record
from deeplynx_nexus_client.models import EdgeResponseDto, GraphResponse
from ..models.item import value_of
from ..models.relationship import Relationship, RelationshipCreate
from ..exceptions import StorageClientError
from .base import BaseResource


class RelationshipsResource(BaseResource):
    """Handles operations related to relationships between items."""

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
                dto = EdgeResponseDto.from_dict(body["value"])
                return Relationship.from_generated(dto)
        if parsed is None or not hasattr(parsed, "id"):
            raise StorageClientError(
                f"Unexpected response to {action} (HTTP {int(response.status_code)})"
            )
        return Relationship.from_generated(parsed)

    def create(self, relationship: RelationshipCreate) -> Relationship:
        """Create a new relationship between two items.

        Args:
            relationship: Relationship creation data

        Returns:
            Created relationship with ID and timestamps

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
        payload = self._edge_payload(relationship)

        params: Dict[str, Any] = {"dataSourceId": self._client._get_data_source_id()}

        response = self._client._request(
            "POST", f"{self._base_path}/edges", json=payload, params=params
        )

        data = response.json()

        # Some DeepLynx endpoints wrap response in 'value' field
        if isinstance(data, dict) and "value" in data:
            data = data["value"]

        return self._parse_relationship(data)

    def _edge_payload(self, relationship: RelationshipCreate) -> Dict[str, Any]:
        """Build an edge-create body. DeepLynx types an edge only by ``relationship_id``."""
        payload: Dict[str, Any] = {
            "origin_id": relationship.from_item_id,
            "destination_id": relationship.to_item_id,
            "properties": relationship.properties,
        }
        if relationship.relationship_type:
            payload["relationship_id"] = self.get_or_create_relationship_type(
                relationship.relationship_type
            )
        return payload

    def get_or_create_relationship_type(self, name: str) -> int:
        """Return the project's relationship-type ID for *name*, creating the type if needed.

        DeepLynx stores an edge's type as a project-level relationship record, and an
        edge-create request that names a missing type fails, so the type is created
        first. IDs are cached per client. A concurrent creator can win the race; the
        type is then looked up again rather than failing.
        """
        cache = self._client._relationship_type_ids
        if name in cache:
            return cache[name]
        type_id = self._find_relationship_type(name)
        if type_id is None:
            try:
                response = self._client._request(
                    "POST",
                    self._relationship_types_path,
                    json={"name": name, "description": name},
                )
                type_id = int(response.json()["id"])
            except StorageClientError:
                type_id = self._find_relationship_type(name)
                if type_id is None:
                    raise
        cache[name] = type_id
        return type_id

    def _find_relationship_type(self, name: str) -> Optional[int]:
        response = self._client._request("GET", self._relationship_types_path)
        data = response.json()
        for relationship_type in data if isinstance(data, list) else []:
            if relationship_type.get("name") == name and not relationship_type.get("isArchived"):
                return int(relationship_type["id"])
        return None

    @property
    def _relationship_types_path(self) -> str:
        return f"/projects/{self._client.config.project_id}/relationships"

    def find_edge(self, from_item_id: int, to_item_id: int) -> Optional[Relationship]:
        """Return the edge from *from_item_id* to *to_item_id*, or ``None`` if there is none.

        DeepLynx allows one edge per ordered pair of records, so the pair names at most
        one edge. DeepLynx answers a missing edge with an error rather than an empty
        result, so any failed lookup returns ``None``: the edge could not be confirmed.
        """
        try:
            response = self._client._request(
                "GET",
                f"{self._base_path}/edges/by-relationship",
                params={"originId": from_item_id, "destinationId": to_item_id},
            )
        except StorageClientError:
            return None
        data = response.json()
        if isinstance(data, dict) and "value" in data:
            data = data["value"]
        return self._parse_relationship(data) if isinstance(data, dict) else None

    def get(self, relationship_id: int) -> Relationship:
        """Get a relationship by ID.

        Raises:
            ItemNotFoundError: If relationship doesn't exist
        """
        organization_id, project_id = self._scope()
        response = api_get_edge_by_id.sync_detailed(
            organization_id, project_id, relationship_id, client=self._generated()
        )
        return self._edge(response, "get relationship")

    def delete(self, relationship_id: int) -> None:
        """Delete a relationship.

        Raises:
            ItemNotFoundError: If relationship doesn't exist
        """
        organization_id, project_id = self._scope()
        api_delete_edge_by_id.sync_detailed(
            organization_id, project_id, relationship_id, client=self._generated()
        )

    def bulk_create(self, relationships: List[RelationshipCreate]) -> List[Relationship]:
        """Create multiple relationships in a single request.

        Args:
            relationships: List of relationships to create

        Returns:
            List of created relationships

        Example:
            ```python
            rels = client.relationships.bulk_create([
                RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="links"),
                RelationshipCreate(from_item_id=2, to_item_id=3, relationship_type="links")
            ])
            ```
        """
        payload = [self._edge_payload(rel) for rel in relationships]

        params = {"dataSourceId": self._client._get_data_source_id()}

        response = self._client._request(
            "POST", f"{self._base_path}/edges/bulk", json=payload, params=params
        )

        data = response.json()

        # API may return edges directly as a list or wrapped in a dict
        if isinstance(data, list):
            edges = data
        else:
            edges = data.get("edges", [])

        return [self._parse_relationship(rel_data) for rel_data in edges]

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
        response = api_get_edges_by_record.sync_detailed(
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
            Graph structure: ``{"nodes": [...], "links": [...]}`` as the server sends it
            (camelCase keys). A body that is not an object is returned as ``{"result": body}``.

        Example:
            ```python
            graph = client.relationships.get_item_graph(123, depth=2)
            ```
        """
        organization_id, project_id = self._scope()
        # The generated operation parses the body as a graph object and fails on any other JSON
        # type, so only its request is used; the body is parsed here to keep the wrapping below.
        request = api_get_graph_data_for_record._get_kwargs(
            organization_id, project_id, item_id, depth=depth
        )
        response = self._client._request(
            request["method"].upper(), request["url"], params=request["params"]
        )
        body = response.json()
        if not isinstance(body, dict):
            return {"result": body}
        return dict(GraphResponse.from_dict(body).to_dict())

    def _parse_relationship(self, data: Dict[str, Any]) -> Relationship:
        """Parse API response data into a Relationship model.

        Args:
            data: Raw API response data

        Returns:
            Parsed Relationship object

        Note:
            created_at and updated_at are optional as some DeepLynx
            deployments may not return these fields.

        Raises:
            ValueError: If required fields are missing from API response
        """
        # DeepLynx API returns camelCase field names per API docs
        from_item_id = data.get("originId")
        to_item_id = data.get("destinationId")

        # Validate required fields
        if from_item_id is None or to_item_id is None:
            import json
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Failed to parse relationship - missing node IDs. Response data: {json.dumps(data, indent=2)}"
            )
            raise ValueError(
                f"API response missing required node ID fields. "
                f"Response keys: {list(data.keys())}. "
                f"Expected 'originId' and 'destinationId'."
            )

        return Relationship(
            id=data["id"],
            from_item_id=from_item_id,
            to_item_id=to_item_id,
            relationship_type=data.get("relationshipName") or data.get("name") or "",
            properties=data.get("properties", {}),
            created_at=data.get("createdAt"),
            updated_at=data.get("lastUpdatedAt"),
            relationship_pair_id=data.get("relationshipId"),
            data_source_id=data.get("dataSourceId"),
        )
