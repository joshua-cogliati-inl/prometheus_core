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

"""Tests for relationship parsing against DeepLynx edge responses."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from prometheus_api.storage_client.async_resources.relationships import (
    AsyncRelationshipsResource,
)
from prometheus_api.storage_client.models.relationship import (
    Relationship,
    RelationshipCreate,
)
from prometheus_api.storage_client.resources.relationships import RelationshipsResource


# get/delete/list go through the generated Nexus client; create still uses the old transport
NEXUS_CLIENT = pytest.mark.requires_nexus_client


class Response(httpx.Response):
    """A real HTTP 200 response: the generated client parses status, headers and body."""

    def __init__(self, payload):
        super().__init__(200, json=payload)


class SyncClient:
    def __init__(self, payload):
        self.config = SimpleNamespace(
            organization_id=1, project_id=2, base_url="http://nexus.test/api/v1"
        )
        self.calls = []
        self._payload = payload

    def _get_data_source_id(self):
        return 7

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return Response(self._payload)


class AsyncClient(SyncClient):
    async def _get_data_source_id(self):
        return 7

    async def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return Response(self._payload)


def edge_payload(**overrides):
    """An edge as the DeepLynx v1 API returns it: ``properties`` is a JSON string."""
    payload = {
        "id": 11,
        "originId": 58,
        "destinationId": 59,
        "relationshipId": None,
        "dataSourceId": 91,
        "projectId": 67,
        "organizationId": 1,
        "properties": '{"strength": "strong"}',
        "lastUpdatedAt": "2026-10-28T22:44:04.4340215Z",
        "isArchived": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"strength": "strong"}', {"strength": "strong"}),
        ("{}", {}),
        ({"already": "a dict"}, {"already": "a dict"}),
        (None, {}),
        ("not json", {}),
        ("[1, 2]", {}),
    ],
)
def test_relationship_properties_accept_deeplynx_string_form(raw, expected):
    """Covers REQ-003-14: edge properties arrive as a JSON string or null."""
    relationship = Relationship(id=1, from_item_id=1, to_item_id=2, properties=raw)

    assert relationship.properties == expected


def test_relationship_create_still_requires_dict_properties():
    """The decoding applies to parsed responses, not to what callers send."""
    with pytest.raises(ValueError):
        RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="t", properties="{}")


async def test_create_parses_string_properties_in_sync_and_async():
    """Covers REQ-003-14: create must not fail on a stringified ``properties`` field."""
    request = RelationshipCreate(from_item_id=58, to_item_id=59, relationship_type="probe")

    sync = RelationshipsResource(SyncClient(edge_payload())).create(request)
    asynchronous = await AsyncRelationshipsResource(AsyncClient(edge_payload())).create(request)

    assert sync.model_dump() == asynchronous.model_dump()
    assert sync.id == 11
    assert (sync.from_item_id, sync.to_item_id) == (58, 59)
    assert sync.properties == {"strength": "strong"}
    assert sync.data_source_id == 91


@NEXUS_CLIENT
async def test_get_parses_wrapped_and_string_properties_in_sync_and_async():
    """Covers REQ-003-10 and REQ-003-14: wrapped responses with string properties parse."""
    payload = {"value": edge_payload(properties="{}")}

    sync = RelationshipsResource(SyncClient(payload)).get(11)
    asynchronous = await AsyncRelationshipsResource(AsyncClient(payload)).get(11)

    assert sync.model_dump() == asynchronous.model_dump()
    assert sync.properties == {}


async def test_bulk_create_parses_string_properties_in_sync_and_async():
    """Covers REQ-003-14 for the bulk endpoint."""
    payload = [edge_payload(id=1), edge_payload(id=2, properties=None)]
    requests = [
        RelationshipCreate(from_item_id=58, to_item_id=59, relationship_type="a"),
        RelationshipCreate(from_item_id=59, to_item_id=58, relationship_type="b"),
    ]

    sync = RelationshipsResource(SyncClient(payload)).bulk_create(requests)
    asynchronous = await AsyncRelationshipsResource(AsyncClient(payload)).bulk_create(requests)

    assert [r.model_dump() for r in sync] == [r.model_dump() for r in asynchronous]
    assert [r.properties for r in sync] == [{"strength": "strong"}, {}]


@NEXUS_CLIENT
async def test_item_relationship_listing_uses_the_record_edges_route_in_sync_and_async():
    """Covers REQ-003-09: the list route returns the related record and the relationship name."""
    payload = [
        {
            "relatedRecordName": "other",
            "relatedRecordId": 59,
            "relatedRecordProjectId": 67,
            "relationshipName": "linked",
        }
    ]
    sync_client, async_client = SyncClient(payload), AsyncClient(payload)

    sync = RelationshipsResource(sync_client).get_item_relationships(58, "outgoing")
    asynchronous = await AsyncRelationshipsResource(async_client).get_item_relationships(
        58, "outgoing"
    )

    assert [r.model_dump() for r in sync] == [r.model_dump() for r in asynchronous]
    assert sync_client.calls == async_client.calls
    method, path, kwargs = sync_client.calls[0]
    assert (method, path) == ("GET", "/organizations/1/projects/2/records/58/edges")
    assert kwargs["params"] == {"isOrigin": True, "page": 1, "pageSize": 100}
    assert (sync[0].from_item_id, sync[0].to_item_id) == (58, 59)
    assert sync[0].relationship_type == "linked"
    assert sync[0].properties == {}


@NEXUS_CLIENT
async def test_item_relationship_listing_maps_incoming_and_combines_both_directions():
    """Covers REQ-003-09: incoming puts the item last; no direction concatenates both."""
    payload = [{"relatedRecordId": 59, "relationshipName": "linked"}]

    incoming = RelationshipsResource(SyncClient(payload)).get_item_relationships(58, "incoming")
    both_client = SyncClient(payload)
    both = RelationshipsResource(both_client).get_item_relationships(58)
    both_async_client = AsyncClient(payload)
    both_async = await AsyncRelationshipsResource(both_async_client).get_item_relationships(58)

    assert (incoming[0].from_item_id, incoming[0].to_item_id) == (59, 58)
    assert [c[2]["params"]["isOrigin"] for c in both_client.calls] == [True, False]
    assert both_client.calls == both_async_client.calls
    assert [(r.from_item_id, r.to_item_id) for r in both] == [(58, 59), (59, 58)]
    assert [r.model_dump() for r in both] == [r.model_dump() for r in both_async]


@NEXUS_CLIENT
async def test_get_and_delete_use_edge_routes_in_sync_and_async():
    """Covers REQ-003-08: get and delete address /edges/{id} through the generated client."""
    sync_client, async_client = SyncClient(edge_payload()), AsyncClient(edge_payload())

    RelationshipsResource(sync_client).get(11)
    RelationshipsResource(sync_client).delete(11)
    await AsyncRelationshipsResource(async_client).get(11)
    await AsyncRelationshipsResource(async_client).delete(11)

    assert sync_client.calls == async_client.calls
    assert [c[:2] for c in sync_client.calls] == [
        ("GET", "/organizations/1/projects/2/edges/11"),
        ("DELETE", "/organizations/1/projects/2/edges/11"),
    ]


@NEXUS_CLIENT
def test_get_without_node_ids_raises_value_error():
    """Covers REQ-003-10: an edge with no origin/destination is rejected, not half-built."""
    client = SyncClient(edge_payload(originId=None, destinationId=None))

    with pytest.raises(ValueError, match="missing required node ID"):
        RelationshipsResource(client).get(11)
