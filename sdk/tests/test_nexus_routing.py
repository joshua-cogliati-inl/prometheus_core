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

"""Tests for routing generated Nexus client calls through the storage client (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
from deeplynx_nexus_client.api.project_tag import api_get_all_tags_project

from prometheus_api.storage_client.nexus_routing import generated_client


class RecordingOwner:
    def __init__(self):
        self.config = SimpleNamespace(base_url="http://nexus.test/api/v1")
        self.calls = []

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return httpx.Response(200, json=[{"id": 3, "name": "a"}])


class AsyncRecordingOwner(RecordingOwner):
    async def _request(self, method, path, **kwargs):
        return super()._request(method, path, **kwargs)


def test_generated_operation_is_sent_through_the_owners_request():
    """Covers REQ-001-13: generated calls reach ``_request`` so auth and errors stay in one place."""
    owner = RecordingOwner()

    result = api_get_all_tags_project.sync_detailed(5, client=generated_client(owner))

    assert owner.calls[0][0] == "GET"
    assert owner.calls[0][1] == "/projects/5/tags"
    assert result.parsed[0].name == "a"
    assert generated_client(owner) is generated_client(owner)


async def test_generated_async_operation_is_sent_through_the_owners_request():
    """Covers REQ-001-13: the async variant is routed through the async ``_request``."""
    owner = AsyncRecordingOwner()

    result = await api_get_all_tags_project.asyncio_detailed(
        5, client=generated_client(owner, asynchronous=True)
    )

    assert owner.calls[0][:2] == ("GET", "/projects/5/tags")
    assert result.parsed[0].id == 3
