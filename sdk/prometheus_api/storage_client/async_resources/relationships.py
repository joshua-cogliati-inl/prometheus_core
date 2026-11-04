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

"""Async relationships resource."""

import json
from typing import Any, Dict, List, Optional
from ..models.item import value_of
from ..models.relationship import Relationship, RelationshipCreate
from ..exceptions import StorageClientError
from ..nexus_client import ensure_nexus_client, generated_client, operation
from .base import AsyncBaseResource


class AsyncRelationshipsResource(AsyncBaseResource):
    """Handles async operations related to relationships between items."""

    def _generated(self) -> Any:
        return generated_client(self._client, asynchronous=True)

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

    async def create(self, relationship: RelationshipCreate) -> Relationship:
        """Create a new relationship between two items asynchronously."""
        payload = {
            "origin_id": relationship.from_item_id,
            "destination_id": relationship.to_item_id,
            "name": relationship.relationship_type,  # API expects 'name' field
            "properties": relationship.properties,
        }

        params: Dict[str, Any] = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/edges", json=payload, params=params
        )

        data = response.json()

        # Some DeepLynx endpoints wrap response in 'value' field
        if isinstance(data, dict) and "value" in data:
            data = data["value"]

        return self._parse_relationship(data)

    async def get(self, relationship_id: int) -> Relationship:
        """Get a relationship by ID.

        Raises:
            ItemNotFoundError: If relationship doesn't exist
        """
        organization_id, project_id = self._scope()
        response = await operation("edge", "api_get_edge_by_id").asyncio_detailed(
            organization_id, project_id, relationship_id, client=self._generated()
        )
        return self._edge(response, "get relationship")

    async def delete(self, relationship_id: int) -> None:
        """Delete a relationship.

        Raises:
            ItemNotFoundError: If relationship doesn't exist
        """
        organization_id, project_id = self._scope()
        await operation("edge", "api_delete_edge_by_id").asyncio_detailed(
            organization_id, project_id, relationship_id, client=self._generated()
        )

    async def bulk_create(self, relationships: List[RelationshipCreate]) -> List[Relationship]:
        """Create multiple relationships in a single request asynchronously."""
        payload = [
            {
                "origin_id": rel.from_item_id,
                "destination_id": rel.to_item_id,
                "name": rel.relationship_type,  # API expects 'name' field
                "properties": rel.properties,
            }
            for rel in relationships
        ]

        params = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/edges/bulk", json=payload, params=params
        )

        data = response.json()

        # API may return edges directly as a list or wrapped in a dict
        if isinstance(data, list):
            edges = data
        else:
            edges = data.get("edges", [])

        return [self._parse_relationship(rel_data) for rel_data in edges]

    async def get_item_relationships(
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
            outgoing = await self.get_item_relationships(item_id, "outgoing")
            incoming = await self.get_item_relationships(item_id, "incoming")
            return outgoing + incoming

        # outgoing: this item is the origin (isOrigin=true); incoming: it is the destination
        is_origin = direction == "outgoing"
        organization_id, project_id = self._scope()
        response = await operation("record", "api_get_edges_by_record").asyncio_detailed(
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

    async def get_item_graph(self, item_id: int, depth: int = 1) -> Dict[str, Any]:
        """Get a graph of relationships starting from an item asynchronously."""
        response = await self._client._request(
            "GET", f"{self._base_path}/records/{item_id}/graph", params={"depth": depth}
        )

        data = response.json()
        return data if isinstance(data, dict) else {"result": data}

    def _parse_relationship(self, data: Dict[str, Any]) -> Relationship:
        """Parse API response data into a Relationship model.

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
            relationship_type=data.get("name", ""),
            properties=data.get("properties", {}),
            created_at=data.get("createdAt"),
            updated_at=data.get("lastUpdatedAt"),
            relationship_pair_id=data.get("relationshipId"),
            data_source_id=data.get("dataSourceId"),
        )
