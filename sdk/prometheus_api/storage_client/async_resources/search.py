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

"""Async search resource."""

from typing import Any, Dict, List, Optional
from deeplynx_nexus_client.models import QueryRecordViewResponseDto
from ..models.item import Item
from ..models.pagination import Page, PageInfo
from .. import paging
from ..paging import parse_paginated
from .base import AsyncBaseResource


class AsyncSearchResource(AsyncBaseResource):
    """Handles async search and query operations."""

    async def query(self, query: str, page: int = 1, page_size: int = 100) -> Page[Item]:
        """Perform a simple text search across items asynchronously."""
        params = {
            "userQuery": query,
            "projectIds": [self._client.config.project_id],
        }

        response = await self._client._request(
            "GET",
            f"/organizations/{self._client.config.organization_id}/query/records",
            params=params,
        )

        data = response.json()
        if isinstance(data, list):
            items = data
        else:
            items = data.get("records", [])

        return self._parse_search_results(items, page, page_size)

    async def advanced_query(
        self,
        filters: List[Dict[str, Any]],
        project_ids: List[int],
        text_search: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[Item]:
        """Perform an advanced, server-paginated search asynchronously."""
        paging.check_page_size(page_size)
        if page < 1:
            raise ValueError("page must be 1 or greater")

        params: Dict[str, Any] = {
            "projects": project_ids,
            "PageNumber": page,
            "PageSize": page_size,
        }
        if text_search:
            params["textSearch"] = text_search

        response = await self._client._request(
            "POST",
            f"/organizations/{self._client.config.organization_id}/query/records/advanced/paginated",
            params=params,
            json=filters,
        )

        return self._parse_paginated_results(response.json())

    async def by_tags(
        self, tags: List[str], match_all: bool = False, page: int = 1, page_size: int = 100
    ) -> Page[Item]:
        """Search for items by tags asynchronously."""
        params = {
            "tags": ",".join(tags),
            "match_all": "true" if match_all else "false",
            "page": page,
            "limit": page_size,
        }

        response = await self._client._request(
            "GET", f"{self._base_path}/records/search/tags", params=params
        )

        return self._parse_search_results(response.json(), page, page_size)

    async def recent(self, limit: int = 100) -> List[Item]:
        """Get the most recently updated items in the active project, newest first.

        Mirrors ``SearchResource.recent``: pages through the paginated, date-sorted query route
        until ``limit`` items are collected or the server has no further page.

        Raises:
            ValueError: If ``limit`` is less than 1
        """
        if limit < 1:
            raise ValueError(f"limit must be 1 or greater for search.recent, got {limit}")

        page_size = min(limit, paging.MAX_PAGE_SIZE)
        items: List[Item] = []
        page = 1
        while len(items) < limit:
            response = await self._client._request(
                "GET",
                f"/organizations/{self._client.config.organization_id}/query/records/paginated",
                params={
                    "projectIds": [self._client.config.project_id],
                    "sortBy": paging.SORT_DATE_NEW,
                    "PageNumber": page,
                    "PageSize": page_size,
                },
            )
            result = self._parse_paginated_results(response.json())
            items.extend(result.items)
            # An empty page ends paging even if the server claims a next one, so a server
            # that never stops cannot hang the loop.
            if not result.items or not result.page_info.has_next:
                break
            page += 1

        return items[:limit]

    def _parse_search_results(self, data: Any, page: int, page_size: int) -> Page[Item]:
        """Parse search results into a Page object."""
        if isinstance(data, list):
            item_list = data
            total_count = len(data)
        else:
            item_list = data.get("records", [])
            total_count = data.get("total", len(item_list))

        items = [self._parse_item(item_data) for item_data in item_list]

        page_info = PageInfo(
            page_number=page,
            page_size=page_size,
            total_count=total_count,
            has_next=page * page_size < total_count,
            has_previous=page > 1,
        )

        return Page(items=items, page_info=page_info)

    def _parse_paginated_results(self, data: Any) -> Page[Item]:
        """Parse a ``PaginatedResponse<QueryRecordViewResponseDto>`` into a ``Page[Item]``."""
        return parse_paginated(data, "query/records/paginated", self._parse_item)

    def _parse_item(self, data: Dict[str, Any]) -> Item:
        """Parse one search result through the generated ``QueryRecordViewResponseDto``.

        Search results carry ``properties`` and ``tags`` as JSON strings; ``Item.from_generated``
        decodes both.
        """
        return Item.from_generated(QueryRecordViewResponseDto.from_dict(data))
