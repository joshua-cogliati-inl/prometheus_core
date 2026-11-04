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

"""Items resource for synchronous operations."""

from typing import Dict, Iterator, List, Optional, Any
from ..models.item import Item, ItemCreate, ItemUpdate
from ..models.pagination import Page, PageInfo
from ..exceptions import StorageClientError
from ..nexus_client import ensure_nexus_client, generated_client, operation
from .base import BaseResource


class ItemsResource(BaseResource):
    """Handles operations related to items (records in DeepLynx)."""

    def create(self, item: ItemCreate) -> Item:
        """Create a new item.

        Args:
            item: Item creation data

        Returns:
            Created item with ID and timestamps

        Example:
            ```python
            item = client.items.create(ItemCreate(
                name="Test Item",
                properties={"key": "value"},
                tags=["important"]
            ))
            ```
        """
        original_id = item.original_id or f"client-{item.name}-{id(item)}"
        organization_id, project_id = self._scope()
        response = operation("record", "api_create_a_record").sync_detailed(
            organization_id,
            project_id,
            client=self._generated(),
            body=item.to_generated(original_id),
            data_source_id=self._client._get_data_source_id(),
        )
        created = self._record(response, "create item")

        # Handle tags if provided
        if item.tags:
            self.add_tags(created.id, item.tags)
            # Refetch to get tags
            return self.get(created.id)

        return created

    def get(self, item_id: int) -> Item:
        """Get an item by ID.

        Args:
            item_id: Item identifier

        Returns:
            Item data

        Raises:
            ItemNotFoundError: If item doesn't exist
        """
        organization_id, project_id = self._scope()
        response = operation("record", "api_get_a_record").sync_detailed(
            organization_id, project_id, item_id, client=self._generated()
        )
        return self._record(response, "get item")

    def update(self, item_id: int, update: ItemUpdate) -> Item:
        """Update an existing item.

        Args:
            item_id: Item identifier
            update: Fields to update

        Returns:
            Updated item

        Example:
            ```python
            updated = client.items.update(
                item_id=123,
                update=ItemUpdate(name="New Name")
            )
            ```
        """
        organization_id, project_id = self._scope()
        response = operation("record", "api_update_a_record").sync_detailed(
            organization_id,
            project_id,
            item_id,
            client=self._generated(),
            body=update.to_generated(),
        )
        return self._record(response, "update item")

    def delete(self, item_id: int) -> None:
        """Delete an item.

        Args:
            item_id: Item identifier

        Raises:
            ItemNotFoundError: If item doesn't exist
        """
        organization_id, project_id = self._scope()
        operation("record", "api_delete_a_record").sync_detailed(
            organization_id, project_id, item_id, client=self._generated()
        )

    def list(
        self, page: int = 1, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Page[Item]:
        """List items with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            filters: Optional filters to apply

        Returns:
            Paginated list of items

        Example:
            ```python
            page = client.items.list(page=1, page_size=50)
            for item in page.items:
                print(item.name)
            ```
        """
        # ``filters`` is free-form, so the request is built here rather than through the typed
        # generated operation; the response is still parsed through the generated record model.
        params: Dict[str, Any] = {"PageNumber": page, "PageSize": page_size}

        if filters:
            params.update(filters)

        response = self._client._request(
            "GET", f"{self._base_path}/records/paginated", params=params
        )

        return self._parse_paginated_items(response.json(), page, page_size)

    def iter_all(
        self, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Iterator[Item]:
        """Iterate over all items with automatic pagination.

        Args:
            page_size: Number of items per page
            filters: Optional filters to apply

        Yields:
            Individual items

        Example:
            ```python
            for item in client.items.iter_all(page_size=50):
                print(item.name)
            ```
        """
        page = 1
        while True:
            result = self.list(page=page, page_size=page_size, filters=filters)
            yield from result.items

            if not result.page_info.has_next:
                break

            page += 1

    def bulk_create(self, items: List[ItemCreate]) -> List[Item]:
        """Create multiple items in a single request.

        Args:
            items: List of items to create

        Returns:
            List of created items

        Example:
            ```python
            items = client.items.bulk_create([
                ItemCreate(name="Item 1"),
                ItemCreate(name="Item 2")
            ])
            ```
        """
        organization_id, project_id = self._scope()
        response = operation("record", "api_create_many_records").sync_detailed(
            organization_id,
            project_id,
            client=self._generated(),
            body=[
                item.to_generated(item.original_id or f"client-{item.name}-{i}")
                for i, item in enumerate(items)
            ],
            data_source_id=self._client._get_data_source_id(),
        )
        if not isinstance(response.parsed, list):
            raise StorageClientError(
                f"Unexpected response to bulk create (HTTP {int(response.status_code)})"
            )
        return [Item.from_generated(record) for record in response.parsed]

    def add_tags(self, item_id: int, tags: List[str]) -> Item:
        """Add tags to an item.

        Args:
            item_id: Item identifier
            tags: List of tag names to add

        Returns:
            Updated item with tags

        Example:
            ```python
            item = client.items.add_tags(123, ["important", "reviewed"])
            ```
        """
        tag_ids = self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return self.get(item_id)
        organization_id, project_id = self._scope()
        for tag_id in tag_ids:
            operation("record", "api_attach_a_tag").sync_detailed(
                organization_id,
                project_id,
                item_id,
                client=self._generated(),
                tag_id=int(tag_id),
            )

        return self.get(item_id)

    def remove_tags(self, item_id: int, tags: List[str]) -> Item:
        """Remove tags from an item.

        Args:
            item_id: Item identifier
            tags: List of tag names to remove

        Returns:
            Updated item without specified tags

        Example:
            ```python
            item = client.items.remove_tags(123, ["old-tag"])
            ```
        """
        tag_ids = self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return self.get(item_id)
        organization_id, project_id = self._scope()
        for tag_id in tag_ids:
            operation("record", "api_unattach_a_tag").sync_detailed(
                organization_id,
                project_id,
                item_id,
                client=self._generated(),
                tag_id=int(tag_id),
            )

        return self.get(item_id)

    def _generated(self) -> Any:
        return generated_client(self._client)

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
        """Parse one record from a raw response through the generated ``RecordResponseDto``.

        The generated parser iterates ``tags`` and ``labels`` without a null check, so a null
        list is dropped first and treated as empty.
        """
        record = {k: v for k, v in data.items() if not (k in ("tags", "labels") and v is None)}
        return Item.from_generated(ensure_nexus_client().models.RecordResponseDto.from_dict(record))
