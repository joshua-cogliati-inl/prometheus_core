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

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from prometheus_api.storage_client.async_resources.tags import AsyncTagsResource
from prometheus_api.storage_client.async_resources.items import AsyncItemsResource
from prometheus_api.storage_client.resources.items import ItemsResource
from prometheus_api.storage_client.exceptions import StorageClientError
from prometheus_api.storage_client.nexus_client import PATH_ENV_VAR, ensure_nexus_client
from prometheus_api.storage_client.resources.tags import TagsResource


@pytest.fixture
def generated_client_available():
    """The tags resource drives the generated client, so skip when it cannot be imported."""
    try:
        ensure_nexus_client()
    except StorageClientError:
        pytest.skip(f"deeplynx_nexus_client is not installed and {PATH_ENV_VAR} is not set")


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _SyncClient:
    def __init__(self):
        self.config = SimpleNamespace(
            organization_id=1, project_id=42, base_url="http://nexus.test/api/v1"
        )
        self.calls = []
        self._responses = [
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": 11, "name": "debug"}),
        ]

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0)


class _AsyncClient:
    def __init__(self, responses):
        self.config = SimpleNamespace(
            organization_id=1, project_id=42, base_url="http://nexus.test/api/v1"
        )
        self.calls = []
        self._responses = list(responses)

    async def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0)


def test_sync_tags_use_project_scope(generated_client_available):
    client = _SyncClient()
    resource = TagsResource(client)

    resolved = resource.resolve_ids([" debug ", "debug", ""])

    assert resolved == [11]
    assert client.calls == [
        ("GET", "/projects/42/tags", {"params": {"hideArchived": True}}),
        (
            "POST",
            "/projects/42/tags",
            {"json": {"name": "debug"}, "headers": {"Content-Type": "application/json"}},
        ),
    ]


def test_async_tags_reject_non_positive_ids(generated_client_available):
    client = _AsyncClient(
        [
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": 0, "name": "debug"}),
        ]
    )
    resource = AsyncTagsResource(client)

    try:
        asyncio.run(resource.resolve_ids(["debug"]))
        raise AssertionError("Expected resolve_ids() to reject non-positive tag ids")
    except ValueError as exc:
        assert "valid positive id" in str(exc)

    assert client.calls == [
        ("GET", "/projects/42/tags", {"params": {"hideArchived": True}}),
        (
            "POST",
            "/projects/42/tags",
            {"json": {"name": "debug"}, "headers": {"Content-Type": "application/json"}},
        ),
    ]


def test_sync_item_add_tags_uses_singular_tag_id_params(generated_client_available):
    client = _SyncClient()
    client.tags = SimpleNamespace(resolve_ids=lambda names: [11, 12])
    client._responses = [
        _Response({}),
        _Response({}),
        httpx.Response(
            200,
            json={
                "id": 99,
                "name": "artifact",
                "properties": "{}",
                "tags": [{"id": 11, "name": "debug"}, {"id": 12, "name": "svg"}],
            },
        ),
    ]
    resource = ItemsResource(client)

    item = resource.add_tags(99, ["debug", "svg"])

    assert item.id == 99
    assert client.calls == [
        ("POST", "/organizations/1/projects/42/records/99/tags", {"params": {"tagId": 11}}),
        ("POST", "/organizations/1/projects/42/records/99/tags", {"params": {"tagId": 12}}),
        ("GET", "/organizations/1/projects/42/records/99", {"params": {"hideArchived": True}}),
    ]


def test_async_item_add_tags_uses_singular_tag_id_params(generated_client_available):
    client = _AsyncClient(
        [
            _Response({}),
            _Response({}),
            httpx.Response(
                200,
                json={
                    "id": 99,
                    "name": "artifact",
                    "properties": "{}",
                    "tags": [{"id": 11, "name": "debug"}, {"id": 12, "name": "svg"}],
                },
            ),
        ]
    )
    client.tags = SimpleNamespace(resolve_ids=_async_return([11, 12]))
    resource = AsyncItemsResource(client)

    item = asyncio.run(resource.add_tags(99, ["debug", "svg"]))

    assert item.id == 99
    assert client.calls == [
        ("POST", "/organizations/1/projects/42/records/99/tags", {"params": {"tagId": 11}}),
        ("POST", "/organizations/1/projects/42/records/99/tags", {"params": {"tagId": 12}}),
        ("GET", "/organizations/1/projects/42/records/99", {"params": {"hideArchived": True}}),
    ]


def _async_return(value):
    async def _inner(_names):
        return value

    return _inner
