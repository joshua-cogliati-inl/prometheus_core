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
from deeplynx_nexus_client.api.olap import api_execute_olap_query
from deeplynx_nexus_client.models import OlapQueryRequestDto
from deeplynx_nexus_client.types import UNSET
from ..exceptions import StorageClientError
from ..models.timeseries import TimeseriesResult
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
    (not ``None``) are in the body; falsy values such as ``0`` or ``""`` are kept. ``record_id``
    goes through ``int()``, so a value that is not a whole number raises before anything is sent.
    """
    body = OlapQueryRequestDto(
        query=UNSET if sql_query is None else sql_query,
        limit=UNSET if limit is None else limit,
        row_stride=UNSET if row_stride is None else row_stride,
        start_row=UNSET if start_row is None else start_row,
        stop_row=UNSET if stop_row is None else stop_row,
        columns=UNSET if columns is None else list(columns),
    )
    request = api_execute_olap_query._get_kwargs(
        organization_id, project_id, int(record_id), body=body, view_name=view_name
    )
    method, path = request.pop("method"), request.pop("url")
    return str(method).upper(), str(path), request


def parse_query_response(data: Any) -> TimeseriesResult:
    """Turn the ``olap/query`` body into a result.

    A missing or null ``columns`` or ``data`` (a window past the end of the file) is an empty
    result. A body that is not a JSON object is a server fault and raises, so it is not mistaken
    for an empty result.

    Raises:
        StorageClientError: If the body is not a JSON object
    """
    if not isinstance(data, dict):
        raise StorageClientError(
            f"Unexpected olap/query response: expected a JSON object, got {type(data).__name__}"
        )
    return TimeseriesResult(columns=data.get("columns") or [], data=data.get("data") or [])


class TimeseriesResource(BaseResource):
    """Handles queries over tabular (timeseries) file records."""

    def query(
        self,
        record_id: int,
        *,
        view_name: str = "data",
        sql_query: Optional[str] = None,
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
            record_id: ID of the record that points at the tabular file or folder of parts. It is
                converted with ``int()``, so a value that is not a whole number raises
                ``ValueError`` before any request is sent.
            view_name: Name of the view the query refers to (letters, digits, underscore)
            sql_query: A single SQL ``SELECT`` over ``view_name``. The server rejects
                statements containing ``COPY``, ``EXPORT``, ``IMPORT``, ``INSERT``, ``UPDATE``,
                ``DELETE``, ``DROP``, ``ALTER``, ``ATTACH``, ``CREATE`` of tables, views or
                secrets, file-reading functions, or a ``;``, as a case-insensitive substring
                match, so a column name such as ``updated`` can be rejected too.
            limit: Maximum rows, 1 to 100000
            row_stride: Keep every Nth row (1 keeps all)
            start_row: First row to include; rows are numbered from 1 in file order
            stop_row: Last row to include
            columns: Column names to keep. The server rejects names with dots or other
                symbols here.

        Returns:
            The column names and rows. A window past the end of the data is an empty result,
            not an error.

        Raises:
            ValidationError: If the server rejects the query or options
            ItemNotFoundError: If the record or its file does not exist
            StorageClientError: If the server's answer is not a JSON object

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
        return parse_query_response(response.json())
