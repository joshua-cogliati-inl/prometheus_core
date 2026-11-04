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

"""Tests for file metadata, download and delete through the generated Nexus client (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from prometheus_api.storage_client.async_resources.files import AsyncFilesResource
from prometheus_api.storage_client.exceptions import StorageClientError
from prometheus_api.storage_client.resources.files import FilesResource

pytestmark = pytest.mark.requires_nexus_client


class SyncClient:
    def __init__(self, response):
        self.config = SimpleNamespace(
            organization_id=1, project_id=2, base_url="http://nexus.test/api/v1"
        )
        self.calls = []
        self._response = response

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._response


class AsyncClient(SyncClient):
    async def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._response


RECORD = {
    "id": 77,
    "name": "data.csv",
    "description": "Experiment results",
    "fileType": "csv",
    "fileSize": 1234,
    "uri": "s3://bucket/data.csv",
    "lastUpdatedAt": "2026-10-28T22:44:04Z",
    "properties": "{}",
}


async def test_get_reads_the_record_and_maps_file_fields_in_sync_and_async():
    """Covers REQ-003-02: file metadata comes from the backing record."""
    sync_client = SyncClient(httpx.Response(200, json=RECORD))
    async_client = AsyncClient(httpx.Response(200, json=RECORD))

    sync = FilesResource(sync_client).get(77)
    asynchronous = await AsyncFilesResource(async_client).get(77)

    assert sync == asynchronous
    assert sync_client.calls[0][:2] == ("GET", "/organizations/1/projects/2/records/77")
    assert (sync.id, sync.name, sync.description) == (77, "data.csv", "Experiment results")
    assert (sync.file_type, sync.size, sync.uri) == ("csv", 1234, "s3://bucket/data.csv")
    assert sync.created_at is None and sync.updated_at is not None


def test_get_tolerates_missing_and_null_file_fields():
    """Covers REQ-003-02: a record with no file fields is metadata with None values."""
    client = SyncClient(httpx.Response(200, json={"id": 5, "fileType": None, "fileSize": None}))

    meta = FilesResource(client).get(5)

    assert meta.name == "" and meta.file_type is None and meta.size is None and meta.uri is None


def test_get_rejects_a_response_that_is_not_a_record():
    """Covers REQ-003-02: an unparseable success response is a StorageClientError."""
    client = SyncClient(httpx.Response(204))

    with pytest.raises(StorageClientError, match="Unexpected response"):
        FilesResource(client).get(5)


async def test_download_writes_the_bytes_and_creates_parent_directories(tmp_path):
    """Covers REQ-003-03: bytes are written as received, creating the target's parent folders."""
    payload = bytes(range(256)) + b"\x00end"
    sync_client = SyncClient(httpx.Response(200, content=payload))
    async_client = AsyncClient(httpx.Response(200, content=payload))
    sync_target = tmp_path / "a" / "b" / "sync.bin"
    async_target = tmp_path / "c" / "async.bin"

    FilesResource(sync_client).download(77, sync_target)
    await AsyncFilesResource(async_client).download(77, async_target)

    assert sync_target.read_bytes() == payload == async_target.read_bytes()
    assert sync_client.calls[0][:2] == ("GET", "/organizations/1/projects/2/files/77")


async def test_delete_calls_the_file_route_and_returns_none_in_sync_and_async():
    """Covers REQ-003-04: delete addresses /files/{id} and returns None."""
    sync_client = SyncClient(httpx.Response(200))
    async_client = AsyncClient(httpx.Response(200))

    assert FilesResource(sync_client).delete(77) is None
    assert await AsyncFilesResource(async_client).delete(77) is None

    assert sync_client.calls == async_client.calls
    assert sync_client.calls[0][:2] == ("DELETE", "/organizations/1/projects/2/files/77")


async def test_upload_sends_one_file_part_with_the_stored_name_in_sync_and_async(tmp_path):
    """Covers REQ-003-01: upload posts a multipart ``file`` part named ``name`` or the file's name."""
    src = tmp_path / "local.txt"
    src.write_bytes(b"hello\x00bytes")
    seen = []

    class Capturing(SyncClient):
        def _request(self, method, path, **kwargs):
            parts = [(key, value[0], value[1].read()) for key, value in kwargs["files"]]
            seen.append((method, path, parts, kwargs.get("params"), kwargs.get("data")))
            return self._response

    class AsyncCapturing(Capturing):
        async def _request(self, method, path, **kwargs):
            return Capturing._request(self, method, path, **kwargs)

    record = httpx.Response(200, json=RECORD)

    FilesResource(Capturing(record)).upload(src)
    FilesResource(Capturing(record)).upload(src, name="custom.txt")
    await AsyncFilesResource(AsyncCapturing(record)).upload(src, name="custom.txt")

    method, path, parts, params, data = seen[0]
    assert (method, path) == ("POST", "/organizations/1/projects/2/files")
    assert parts == [("file", "local.txt", b"hello\x00bytes")]
    # No data source or description is sent; ``embed=false`` is the generated default (and the
    # server's), so the project default data source is still used
    assert params == {"embed": False} and data is None
    assert seen[1][2] == [("file", "custom.txt", b"hello\x00bytes")]
    assert seen[2] == seen[1]


async def test_upload_returns_the_parsed_record_even_with_null_tag_lists(tmp_path):
    """Covers REQ-003-01: the response record becomes FileMetadata; null tags do not break it."""
    src = tmp_path / "f.txt"
    src.write_text("x")
    record = httpx.Response(200, json={**RECORD, "tags": None, "labels": None})

    sync = FilesResource(SyncClient(record)).upload(src)
    asynchronous = await AsyncFilesResource(AsyncClient(record)).upload(src)

    assert sync == asynchronous
    assert (sync.id, sync.name, sync.file_type, sync.size) == (77, "data.csv", "csv", 1234)


async def test_upload_rejects_a_missing_path_before_any_request(tmp_path):
    """Covers REQ-003-01 and BEH-003-01: a missing local file raises ValueError, sending nothing."""
    sync_client, async_client = SyncClient(None), AsyncClient(None)
    missing = tmp_path / "nope.txt"

    with pytest.raises(ValueError, match="does not exist"):
        FilesResource(sync_client).upload(missing)
    with pytest.raises(ValueError, match="does not exist"):
        await AsyncFilesResource(async_client).upload(missing)

    assert sync_client.calls == [] and async_client.calls == []


async def test_upload_sends_the_description_in_a_metadata_part(tmp_path):
    """Covers REQ-003-18: a description travels as a metadata JSON part the server requires."""
    src = tmp_path / "local.txt"
    src.write_text("body")
    seen = []

    class Capturing(SyncClient):
        def _request(self, method, path, **kwargs):
            seen.append(
                {key: (value[0], value[1].read(), value[2]) for key, value in kwargs["files"]}
            )
            return self._response

    class AsyncCapturing(Capturing):
        async def _request(self, method, path, **kwargs):
            return Capturing._request(self, method, path, **kwargs)

    record = httpx.Response(200, json=RECORD)

    FilesResource(Capturing(record)).upload(
        src, name="custom.txt", description="Experiment results"
    )
    await AsyncFilesResource(AsyncCapturing(record)).upload(src, description="Éxperiment ✓")

    import json

    sync_parts, async_parts = seen
    assert set(sync_parts) == {"file", "metadata"}
    assert sync_parts["file"][:2] == ("custom.txt", b"body")
    assert sync_parts["metadata"][0] == "metadata.json"
    assert sync_parts["metadata"][2] == "application/json"
    assert json.loads(sync_parts["metadata"][1]) == {
        "Name": "custom.txt",
        "Description": "Experiment results",
        "Properties": {},
    }
    # Name repeats the file part's name, and non-ASCII text survives as UTF-8
    assert json.loads(async_parts["metadata"][1])["Name"] == async_parts["file"][0] == "local.txt"
    assert json.loads(async_parts["metadata"][1])["Description"] == "Éxperiment ✓"


@pytest.mark.parametrize("description", [None, ""])
def test_upload_without_a_description_sends_no_metadata_part(tmp_path, description):
    """Covers REQ-003-18: without a description only the file part is sent."""
    src = tmp_path / "local.txt"
    src.write_text("body")
    seen = []

    class Capturing(SyncClient):
        def _request(self, method, path, **kwargs):
            seen.append([key for key, _ in kwargs["files"]])
            return self._response

    FilesResource(Capturing(httpx.Response(200, json=RECORD))).upload(src, description=description)

    assert seen == [["file"]]
