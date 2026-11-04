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

"""Timeseries resource for asynchronous operations."""

from typing import Optional, Sequence
from ..models.timeseries import TimeseriesResult
from ..resources.timeseries import build_query_request, parse_query_result
from .base import AsyncBaseResource


class AsyncTimeseriesResource(AsyncBaseResource):
    """Handles async queries over tabular (timeseries) file records."""

    async def query(
        self,
        record_id: int,
        view_name: str = "data",
        sql_query: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        row_stride: Optional[int] = None,
        start_row: Optional[int] = None,
        stop_row: Optional[int] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> TimeseriesResult:
        """Query the rows of a tabular file record asynchronously.

        Takes the same arguments and returns the same result as
        ``TimeseriesResource.query``; see its documentation for the server's rules.
        """
        config = self._client.config
        method, path, request = build_query_request(
            config.organization_id,
            config.project_id,
            record_id,
            view_name,
            sql_query,
            limit,
            row_stride,
            start_row,
            stop_row,
            columns,
        )
        response = await self._client._request(method, path, **request)
        return parse_query_result(response.json())
