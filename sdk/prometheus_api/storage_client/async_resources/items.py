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

"""Async items resource."""

import logging
from typing import AsyncIterator, Dict, List, Optional, Any
from importlib.metadata import version as pkg_version
from ..models.item import Item, ItemCreate, ItemUpdate, Tag
from ..models.pagination import Page, PageInfo
from ..exceptions import StorageClientError
from ..nexus_client import generated_client, operation
from .base import AsyncBaseResource

logger = logging.getLogger(__name__)


class AsyncItemsResource(AsyncBaseResource):
    """Handles async operations related to items."""

    async def create(self, item: ItemCreate) -> Item:
        """Create a new item asynchronously."""
        original_id = item.original_id or f"client-{item.name}-{id(item)}"
        organization_id, project_id = self._scope()
        response = await operation("record", "api_create_a_record").asyncio_detailed(
            organization_id,
            project_id,
            client=self._generated(),
            body=item.to_generated(original_id),
            data_source_id=await self._client._get_data_source_id(),
        )
        created = self._record(response, "create item")

        if item.tags:
            await self.add_tags(created.id, item.tags)
            return await self.get(created.id)

        return created

    async def get(self, item_id: int) -> Item:
        """Get an item by ID asynchronously."""
        organization_id, project_id = self._scope()
        response = await operation("record", "api_get_a_record").asyncio_detailed(
            organization_id, project_id, item_id, client=self._generated()
        )
        return self._record(response, "get item")

    async def update(self, item_id: int, update: ItemUpdate) -> Item:
        """Update an existing item asynchronously."""
        organization_id, project_id = self._scope()
        response = await operation("record", "api_update_a_record").asyncio_detailed(
            organization_id,
            project_id,
            item_id,
            client=self._generated(),
            body=update.to_generated(),
        )
        return self._record(response, "update item")

    async def delete(self, item_id: int) -> None:
        """Delete an item asynchronously."""
        organization_id, project_id = self._scope()
        await operation("record", "api_delete_a_record").asyncio_detailed(
            organization_id, project_id, item_id, client=self._generated()
        )

    async def list(
        self, page: int = 1, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Page[Item]:
        """List items with pagination asynchronously."""
        params: Dict[str, Any] = {"PageNumber": page, "PageSize": page_size}

        if filters:
            params.update(filters)

        response = await self._client._request(
            "GET", f"{self._base_path}/records/paginated", params=params
        )

        return self._parse_paginated_items(response.json(), page, page_size)

    async def iter_all(
        self, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Item]:
        """Iterate over all items with automatic pagination asynchronously."""
        page = 1
        while True:
            result = await self.list(page=page, page_size=page_size, filters=filters)
            for item in result.items:
                yield item

            if not result.page_info.has_next:
                break

            page += 1

    async def bulk_create(self, items: List[ItemCreate]) -> List[Item]:
        """Create multiple items in a single request asynchronously."""
        payload = [
            {
                "name": item.name,
                "description": item.description or item.name,
                "properties": item.properties,
                "original_id": item.original_id or f"client-{item.name}-{i}",
                "class_id": item.class_id,
            }
            for i, item in enumerate(items)
        ]

        params = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/records/bulk", json=payload, params=params
        )

        data = response.json()
        # API returns array directly
        if isinstance(data, list):
            return [self._parse_item(item_data) for item_data in data]
        else:
            return [self._parse_item(item_data) for item_data in data.get("records", [])]

    async def add_tags(self, item_id: int, tags: List[str]) -> Item:
        """Add tags to an item asynchronously. Tag names are resolved to IDs."""
        tag_ids = await self._client.tags.resolve_ids(tags)
        logger.info(
            "prometheus-api %s add_tags: item=%s names=%r resolved_ids=%r",
            pkg_version("prometheus-api"),
            item_id,
            tags,
            tag_ids,
        )
        if not tag_ids:
            return await self.get(item_id)
        for tag_id in tag_ids:
            await self._client._request(
                "POST",
                f"{self._base_path}/records/{item_id}/tags",
                params={"tagId": int(tag_id)},
            )

        return await self.get(item_id)

    async def remove_tags(self, item_id: int, tags: List[str]) -> Item:
        """Remove tags from an item asynchronously."""
        tag_ids = await self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return await self.get(item_id)
        for tag_id in tag_ids:
            await self._client._request(
                "DELETE",
                f"{self._base_path}/records/{item_id}/tags",
                params={"tagId": int(tag_id)},
            )

        return await self.get(item_id)

    def _generated(self) -> Any:
        return generated_client(self._client, asynchronous=True)

    def _scope(self) -> tuple:
        config = self._client.config
        return config.organization_id, config.project_id

    @staticmethod
    def _record(response: Any, action: str) -> Item:
        if response.parsed is None or not hasattr(response.parsed, "id"):
            raise StorageClientError(
                f"Unexpected response to {action} (HTTP {int(response.status_code)})"
            )
        return Item.from_generated(response.parsed)

    def _parse_paginated_items(self, data: Any, page: int, page_size: int) -> Page[Item]:
        """Parse a ``PaginatedResponse<RecordResponseDto>`` into a ``Page[Item]``.

        The server returns ``items: null`` for an empty result, so a missing or null ``items``
        is an empty page. The server's own paging numbers are used when present.
        """
        items = [self._parse_item(item_data) for item_data in (data.get("items") or [])]
        total_count = data.get("totalCount", len(items))
        page_info = PageInfo(
            page_number=data.get("pageNumber", page),
            page_size=data.get("pageSize", page_size),
            total_count=total_count,
            has_next=data.get("hasNext", False),
            has_previous=data.get("hasPrevious", page > 1),
        )
        return Page(items=items, page_info=page_info)

    def _parse_item(self, data: Dict[str, Any]) -> Item:
        """Parse API response data into an Item model."""
        import json as json_lib
        from datetime import datetime

        # Parse properties if it's a JSON string
        properties = data.get("properties", {})
        if isinstance(properties, str):
            try:
                properties = json_lib.loads(properties)
            except (TypeError, ValueError):
                properties = {}

        # Parse timestamp
        timestamp_str = data.get("lastUpdatedAt")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Map DeepLynx fields to our generic model (API uses camelCase in response)
        return Item(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            properties=properties,
            class_id=data.get("classId"),
            original_id=data.get("originalId"),
            created_at=timestamp,
            updated_at=timestamp,
            tags=[Tag(id=t.get("id"), name=t.get("name", "")) for t in (data.get("tags") or [])],
            metatype_id=data.get("classId"),
            metatype_name=data.get("className"),
            data_source_id=data.get("dataSourceId"),
        )
