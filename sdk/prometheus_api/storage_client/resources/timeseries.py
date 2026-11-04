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

"""Timeseries resource for synchronous operations."""

from typing import Any, Dict, Optional, Sequence, Tuple
from ..models.timeseries import TimeseriesResult
from ..nexus_client import models, operation
from .base import BaseResource


def build_query_request(
    organization_id: int,
    project_id: int,
    record_id: int,
    view_name: str,
    sql_query: Optional[str],
    limit: Optional[int],
    row_stride: Optional[int],
    start_row: Optional[int],
    stop_row: Optional[int],
    columns: Optional[Sequence[str]],
) -> Tuple[str, str, Dict[str, Any]]:
    """The ``olap/query`` request as ``(method, path, request kwargs)``.

    Built from the generated operation and ``OlapQueryRequestDto``, so the path and the body's
    camelCase names come from the Nexus API description. Only the options the caller provided
    (not ``None``) are in the body; falsy values such as ``0`` or ``""`` are kept.
    """
    candidates = {
        "query": sql_query,
        "limit": limit,
        "row_stride": row_stride,
        "start_row": start_row,
        "stop_row": stop_row,
        "columns": list(columns) if columns is not None else None,
    }
    body = models().OlapQueryRequestDto(**{k: v for k, v in candidates.items() if v is not None})
    request = operation("olap", "api_execute_olap_query")._get_kwargs(
        organization_id, project_id, record_id, body=body, view_name=view_name
    )
    method, path = request.pop("method"), request.pop("url")
    return str(method).upper(), str(path), request


def parse_query_result(data: Any) -> TimeseriesResult:
    """A ``TimeseriesResult`` from the ``{columns, data}`` body; null or missing means empty.

    Parsed here rather than by the generated ``PlotDataDto``, which fails on a null ``data``.
    """
    if not isinstance(data, dict):
        return TimeseriesResult()
    return TimeseriesResult(columns=data.get("columns") or [], data=data.get("data") or [])


class TimeseriesResource(BaseResource):
    """Handles queries over tabular (timeseries) file records."""

    def query(
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
        """Query the rows of a tabular file (csv or parquet) record.

        Calls ``POST .../records/{record_id}/olap/query``. The server exposes the file as a
        temporary SQL view called ``view_name`` and runs ``sql_query`` against it, so the
        query must mention ``view_name``. Without a query it returns ``SELECT * FROM`` the
        view, limited to ``limit`` rows (the server's default is 20).

        Args:
            record_id: ID of the record that points at the tabular file or folder of parts
            view_name: Name of the view the query refers to (letters, digits, underscore)
            sql_query: A single SQL ``SELECT`` over ``view_name``. The server rejects
                statements containing ``COPY``, ``EXPORT``, ``IMPORT``, ``INSERT``, ``UPDATE``,
                ``DELETE``, ``DROP``, ``ALTER``, ``ATTACH``, ``CREATE`` of tables, views or
                secrets, file-reading functions, or a ``;``, as a case-insensitive substring
                match, so a column name such as ``updated`` can be rejected too.
                Quote column names that contain dots, for example ``"a.b"``.
            limit: Maximum rows, 1 to 100000
            row_stride: Keep every Nth row (1 keeps all)
            start_row: First row to include; rows are numbered from 1 in file order
            stop_row: Last row to include
            columns: Column names to keep. Names with dots or other symbols are rejected by
                the server here; select them with ``sql_query`` instead.

        Returns:
            The column names and rows. A window past the end of the data is an empty result,
            not an error.

        Raises:
            ValidationError: If the server rejects the query or options
            ItemNotFoundError: If the record or its file does not exist

        Note:
            Each call opens a fresh query engine on the server and can take many seconds on
            large files. Raise ``ConnectionConfig.timeout`` if requests time out.

        Example:
            ```python
            result = client.timeseries.query(
                record_id=123,
                sql_query='SELECT "Timestamp", power FROM data WHERE power > 5',
            )
            print(result.columns, result.data[:3])
            ```
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
        response = self._client._request(method, path, **request)
        return parse_query_result(response.json())
