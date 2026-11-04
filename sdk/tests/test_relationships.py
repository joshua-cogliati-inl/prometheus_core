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
from prometheus_api.storage_client.exceptions import APIError, ValidationError
from prometheus_api.storage_client.models.relationship import (
    Relationship,
    RelationshipCreate,
)
from prometheus_api.storage_client.resources.relationships import RelationshipsResource


# Everything but the model tests goes through the generated Nexus client
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


@NEXUS_CLIENT
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


class RoutedClient(SyncClient):
    """Answers by route, as the server does, and can fail an edge create like the server."""

    def __init__(self, relationships=None, fail_edges=0):
        super().__init__(None)
        self.relationships = list(relationships or [])
        self.fail_edges = fail_edges
        self.next_id = 100

    def _answer(self, method, path, kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/relationships") and method == "GET":
            return Response(self.relationships)
        if path.endswith("/relationships") and method == "POST":
            self.next_id += 1
            created = {"id": self.next_id, "name": kwargs["json"]["name"]}
            self.relationships.append(created)
            return Response(created)
        if path.endswith("/edges/bulk"):
            return Response(
                [
                    edge_payload(id=i + 1, relationshipId=b.get("relationship_id"))
                    for i, b in enumerate(kwargs["json"])
                ]
            )
        if path.endswith("/edges"):
            if self.fail_edges:
                self.fail_edges -= 1
                name = kwargs["json"]["relationship_name"]
                raise APIError(
                    f"Relationship with name '{name}' not found in organization 1", status_code=500
                )
            rid = next(
                (
                    r["id"]
                    for r in self.relationships
                    if r["name"].lower() == kwargs["json"]["relationship_name"].lower()
                ),
                None,
            )
            return Response(edge_payload(relationshipId=rid))
        raise AssertionError(f"unexpected request {method} {path}")

    def _request(self, method, path, **kwargs):
        return self._answer(method, path, kwargs)


class AsyncRoutedClient(RoutedClient):
    async def _get_data_source_id(self):
        return 7

    async def _request(self, method, path, **kwargs):
        return self._answer(method, path, kwargs)


def edge_calls(client):
    return [c for c in client.calls if c[1].endswith("/edges")]


def type_posts(client):
    return [c for c in client.calls if c[1].endswith("/relationships") and c[0] == "POST"]


LINK = RelationshipCreate(from_item_id=58, to_item_id=59, relationship_type="depends_on")


@NEXUS_CLIENT
async def test_create_sends_the_type_by_name_without_extra_requests_in_sync_and_async():
    """Covers REQ-003-07: a known type costs one request and its name reaches the server."""
    known = [{"id": 5, "name": "depends_on"}]
    sync_client, async_client = RoutedClient(known), AsyncRoutedClient(known)

    sync = RelationshipsResource(sync_client).create(LINK)
    asynchronous = await AsyncRelationshipsResource(async_client).create(LINK)

    assert sync.model_dump() == asynchronous.model_dump()
    assert [c[:2] for c in sync_client.calls] == [("POST", "/organizations/1/projects/2/edges")]
    kwargs = sync_client.calls[0][2]
    assert kwargs["json"]["relationship_name"] == "depends_on"
    assert kwargs["json"]["origin_id"] == 58 and kwargs["json"]["destination_id"] == 59
    assert kwargs["params"] == {"dataSourceId": 7}
    assert sync.relationship_type == "depends_on" and sync.relationship_pair_id == 5


@NEXUS_CLIENT
async def test_create_makes_a_missing_type_and_retries_once_in_sync_and_async():
    """Covers REQ-003-15: an unknown type is created at organization level, then the edge retried."""
    sync_client, async_client = RoutedClient(fail_edges=1), AsyncRoutedClient(fail_edges=1)

    sync = RelationshipsResource(sync_client).create(LINK)
    asynchronous = await AsyncRelationshipsResource(async_client).create(LINK)

    assert sync.model_dump() == asynchronous.model_dump()
    assert [(c[0], c[1]) for c in sync_client.calls] == [
        ("POST", "/organizations/1/projects/2/edges"),
        ("GET", "/organizations/1/relationships"),
        ("POST", "/organizations/1/relationships"),
        ("POST", "/organizations/1/projects/2/edges"),
    ]
    assert sync_client.calls == async_client.calls
    assert type_posts(sync_client)[0][2]["json"] == {"name": "depends_on"}
    assert sync.relationship_type == "depends_on" and sync.relationship_pair_id == 101


@NEXUS_CLIENT
async def test_create_reuses_a_type_that_appeared_under_another_case():
    """Covers REQ-003-15: a case-insensitive match is reused, not created a second time."""
    existing = [{"id": 9, "name": "Depends_On"}]
    sync_client = RoutedClient(existing, fail_edges=1)

    result = RelationshipsResource(sync_client).create(LINK)

    assert type_posts(sync_client) == []
    assert result.relationship_pair_id == 9


@NEXUS_CLIENT
async def test_create_without_auto_creation_raises_a_validation_error_in_sync_and_async():
    """Covers REQ-003-15: with the option off, the unknown type is reported, not hidden in a 500."""
    sync_client, async_client = RoutedClient(fail_edges=1), AsyncRoutedClient(fail_edges=1)

    with pytest.raises(ValidationError, match="depends_on"):
        RelationshipsResource(sync_client).create(LINK, create_type_if_missing=False)
    with pytest.raises(ValidationError, match="depends_on"):
        await AsyncRelationshipsResource(async_client).create(LINK, create_type_if_missing=False)

    assert type_posts(sync_client) == []
    assert len(edge_calls(sync_client)) == 1


@NEXUS_CLIENT
async def test_create_does_not_retry_other_failures():
    """Covers REQ-003-15: only the missing-type failure triggers a lookup and a retry."""

    class Failing(RoutedClient):
        def _request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            raise APIError("database unavailable", status_code=500)

    client = Failing()

    with pytest.raises(APIError, match="database unavailable"):
        RelationshipsResource(client).create(LINK)

    assert len(client.calls) == 1


@NEXUS_CLIENT
async def test_create_gives_up_after_one_retry():
    """Covers REQ-003-15: if the retry still reports the type missing, that error is raised."""
    client = RoutedClient(fail_edges=2)

    with pytest.raises(APIError, match="not found"):
        RelationshipsResource(client).create(LINK)

    assert len(edge_calls(client)) == 2


@NEXUS_CLIENT
async def test_bulk_create_sends_type_ids_and_creates_each_missing_type_once():
    """Covers REQ-003-15: bulk resolves types up front; the bulk route only understands IDs."""
    requests = [
        RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="links"),
        RelationshipCreate(from_item_id=2, to_item_id=3, relationship_type="LINKS"),
        RelationshipCreate(from_item_id=3, to_item_id=4, relationship_type="owns"),
    ]
    existing = [{"id": 7, "name": "owns"}]
    sync_client, async_client = RoutedClient(existing), AsyncRoutedClient(existing)

    sync = RelationshipsResource(sync_client).bulk_create(requests)
    asynchronous = await AsyncRelationshipsResource(async_client).bulk_create(requests)

    assert [r.model_dump() for r in sync] == [r.model_dump() for r in asynchronous]
    assert [c[1] for c in type_posts(sync_client)] == ["/organizations/1/relationships"]
    assert [c[2]["json"] for c in type_posts(sync_client)] == [{"name": "links"}]
    bulk = [c for c in sync_client.calls if c[1].endswith("/edges/bulk")]
    assert [e["relationship_id"] for e in bulk[0][2]["json"]] == [101, 101, 7]
    assert "relationship_name" not in bulk[0][2]["json"][0]
    assert [r.relationship_type for r in sync] == ["links", "links", "owns"]
    assert sync[0].properties == {"strength": "strong"}


@NEXUS_CLIENT
async def test_bulk_create_without_auto_creation_raises_before_sending():
    """Covers REQ-003-15: a missing type stops the batch before any edge is created."""
    client = RoutedClient([{"id": 7, "name": "owns"}])
    requests = [
        RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="owns"),
        RelationshipCreate(from_item_id=2, to_item_id=3, relationship_type="links"),
    ]

    with pytest.raises(ValidationError, match="links"):
        RelationshipsResource(client).bulk_create(requests, create_type_if_missing=False)

    assert [c for c in client.calls if c[1].endswith("/edges/bulk")] == []
    assert type_posts(client) == []


@NEXUS_CLIENT
def test_bulk_create_with_no_types_skips_the_type_lookup():
    """Covers REQ-003-15: blank types need no relationship list request."""
    client = RoutedClient()
    blank = RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="")

    result = RelationshipsResource(client).bulk_create([blank])

    assert [c[1] for c in client.calls] == ["/organizations/1/projects/2/edges/bulk"]
    assert "relationship_id" not in client.calls[0][2]["json"][0]
    assert result[0].relationship_type == ""


GRAPH = {
    "nodes": [
        {"id": 249, "label": "a", "type": "root", "classId": None, "className": None},
        {"id": 250, "label": "b", "type": "node", "classId": 3, "className": "Sensor"},
    ],
    "links": [
        {
            "edgeId": 67,
            "relationshipId": 36,
            "relationshipName": "depends_on",
            "source": 249,
            "target": 250,
        }
    ],
}


@NEXUS_CLIENT
async def test_item_graph_returns_the_server_graph_in_sync_and_async():
    """Covers REQ-003-11: the graph route is called with the depth and the graph is unchanged."""
    sync_client, async_client = SyncClient(GRAPH), AsyncClient(GRAPH)

    sync = RelationshipsResource(sync_client).get_item_graph(249, depth=2)
    asynchronous = await AsyncRelationshipsResource(async_client).get_item_graph(249, depth=2)

    assert sync == asynchronous == GRAPH
    assert sync_client.calls == async_client.calls
    method, path, kwargs = sync_client.calls[0]
    assert (method, path) == ("GET", "/organizations/1/projects/2/records/249/graph")
    assert kwargs["params"] == {"depth": 2}


@NEXUS_CLIENT
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, {}),
        ({"nodes": None, "links": None}, {"nodes": None, "links": None}),
        ([1, 2], {"result": [1, 2]}),
        ("text", {"result": "text"}),
    ],
)
def test_item_graph_handles_empty_null_and_non_object_bodies(payload, expected):
    """Covers REQ-003-11: an empty graph is a dict, and a non-object body is wrapped."""
    assert RelationshipsResource(SyncClient(payload)).get_item_graph(1) == expected
