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
from deeplynx_nexus_client.api.record import api_attach_a_tag
from deeplynx_nexus_client.api.record import api_create_a_record
from deeplynx_nexus_client.api.record import api_create_many_records
from deeplynx_nexus_client.api.record import api_delete_a_record
from deeplynx_nexus_client.api.record import api_get_a_record
from deeplynx_nexus_client.api.record import api_unattach_a_tag
from deeplynx_nexus_client.api.record import api_update_a_record
from deeplynx_nexus_client.models import RecordResponseDto
from ..models.item import Item, ItemCreate, ItemUpdate
from ..models.pagination import Page
from ..exceptions import StorageClientError
from ..paging import check_list_filters, check_page_size, parse_paginated
from .base import AsyncBaseResource

logger = logging.getLogger(__name__)


class AsyncItemsResource(AsyncBaseResource):
    """Handles async operations related to items."""

    async def create(self, item: ItemCreate) -> Item:
        """Create a new item asynchronously."""
        original_id = item.original_id or f"client-{item.name}-{id(item)}"
        organization_id, project_id = self._scope()
        response = await api_create_a_record.asyncio_detailed(
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
        response = await api_get_a_record.asyncio_detailed(
            organization_id, project_id, item_id, client=self._generated()
        )
        return self._record(response, "get item")

    async def update(self, item_id: int, update: ItemUpdate) -> Item:
        """Update an existing item asynchronously."""
        organization_id, project_id = self._scope()
        response = await api_update_a_record.asyncio_detailed(
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
        await api_delete_a_record.asyncio_detailed(
            organization_id, project_id, item_id, client=self._generated()
        )

    async def list(
        self, page: int = 1, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Page[Item]:
        """List items with pagination asynchronously."""
        check_list_filters(filters)
        check_page_size(page_size)
        # ``filters`` is free-form, so the request is built here rather than through the typed
        # generated operation; the response is still parsed through the generated record model.
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

            # An empty page ends paging even if the server claims a next one.
            if not result.items or not result.page_info.has_next:
                break

            page += 1

    async def bulk_create(self, items: List[ItemCreate]) -> List[Item]:
        """Create multiple items in a single request asynchronously."""
        organization_id, project_id = self._scope()
        response = await api_create_many_records.asyncio_detailed(
            organization_id,
            project_id,
            client=self._generated(),
            body=[
                item.to_generated(item.original_id or f"client-{item.name}-{i}")
                for i, item in enumerate(items)
            ],
            data_source_id=await self._client._get_data_source_id(),
        )
        if not isinstance(response.parsed, list):
            raise StorageClientError(
                f"Unexpected response to bulk create (HTTP {int(response.status_code)})"
            )
        return [Item.from_generated(record) for record in response.parsed]

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
        organization_id, project_id = self._scope()
        for tag_id in tag_ids:
            await api_attach_a_tag.asyncio_detailed(
                organization_id,
                project_id,
                item_id,
                client=self._generated(),
                tag_id=int(tag_id),
            )

        return await self.get(item_id)

    async def remove_tags(self, item_id: int, tags: List[str]) -> Item:
        """Remove tags from an item asynchronously."""
        tag_ids = await self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return await self.get(item_id)
        organization_id, project_id = self._scope()
        for tag_id in tag_ids:
            await api_unattach_a_tag.asyncio_detailed(
                organization_id,
                project_id,
                item_id,
                client=self._generated(),
                tag_id=int(tag_id),
            )

        return await self.get(item_id)

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
        """Parse a ``PaginatedResponse<RecordResponseDto>`` into a ``Page[Item]``."""
        return parse_paginated(data, "records/paginated", self._parse_item)

    def _parse_item(self, data: Dict[str, Any]) -> Item:
        """Parse one record from a raw response through the generated ``RecordResponseDto``.

        The generated parser iterates ``tags`` and ``labels`` without a null check, so a null
        list is dropped first and treated as empty.
        """
        record = {k: v for k, v in data.items() if not (k in ("tags", "labels") and v is None)}
        return Item.from_generated(RecordResponseDto.from_dict(record))
