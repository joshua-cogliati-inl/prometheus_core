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

"""Tests for chunked file uploads through the generated Nexus client (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from prometheus_api.storage_client.async_resources.files import AsyncFilesResource
from prometheus_api.storage_client.exceptions import APIError
from prometheus_api.storage_client.resources.files import FilesResource

pytestmark = pytest.mark.requires_nexus_client

BASE = "/organizations/1/projects/2/files/upload"
RECORD = {"id": 77, "name": "big.bin", "description": "d", "fileType": "bin", "fileSize": 10}


class Recorder:
    """A fake client that answers the four chunked-upload routes like the server does."""

    def __init__(self, fail_on_chunk=None, start_body=None, fail_cancel=False):
        self.config = SimpleNamespace(
            organization_id=1, project_id=2, base_url="http://nexus.test/api/v1"
        )
        self.calls = []
        self.fail_on_chunk = fail_on_chunk
        self.fail_cancel = fail_cancel
        self.start_body = {"uploadId": "up-1", "chunkSize": 100000000, "totalChunks": 1}
        if start_body is not None:
            self.start_body = start_body

    @staticmethod
    def _read(key, content):
        """The part's bytes; the plain form fields (everything but the chunk) as text."""
        data = content.read() if hasattr(content, "read") else content
        return data if key == "chunk" else data.decode()

    def _answer(self, method, path, kwargs):
        record = {"method": method, "path": path}
        if "files" in kwargs:
            record["parts"] = {
                key: (value[0], self._read(key, value[1])) for key, value in kwargs["files"]
            }
        if "json" in kwargs:
            record["json"] = kwargs["json"]
        self.calls.append(record)
        if path.endswith("/start"):
            return httpx.Response(200, json=self.start_body)
        if path.endswith("/chunk"):
            number = int(record["parts"]["chunkNumber"][1])
            if self.fail_on_chunk == number:
                raise APIError("chunk rejected", status_code=500)
            return httpx.Response(200, json={"chunkUploadStatus": "success"})
        if path.endswith("/complete"):
            return httpx.Response(200, json=RECORD)
        if method == "DELETE":
            if self.fail_cancel:
                raise APIError("cancel failed", status_code=500)
            return httpx.Response(200, json={"message": "cancelled"})
        raise AssertionError(f"unexpected request {method} {path}")

    def _request(self, method, path, **kwargs):
        return self._answer(method, path, kwargs)


class AsyncRecorder(Recorder):
    async def _request(self, method, path, **kwargs):
        return self._answer(method, path, kwargs)


def file_of(tmp_path, size):
    path = tmp_path / "big.bin"
    path.write_bytes(bytes(range(256)) * (size // 256) + bytes(range(size % 256)))
    return path


def kinds(client):
    return [c["path"].rsplit("/", 1)[-1] for c in client.calls]


@pytest.mark.parametrize(
    ("size", "chunk", "expected"), [(10, 4, 3), (8, 4, 2), (1, 4, 1), (4, 4, 1)]
)
async def test_chunks_are_counted_by_what_is_sent_in_sync_and_async(
    tmp_path, size, chunk, expected
):
    """Covers REQ-003-05: chunks go out zero-based and the completion carries the count sent."""
    path = file_of(tmp_path, size)
    sync_client, async_client = Recorder(), AsyncRecorder()

    sync = FilesResource(sync_client).upload_chunked(path, chunk_size=chunk)
    asynchronous = await AsyncFilesResource(async_client).upload_chunked(path, chunk_size=chunk)

    assert sync == asynchronous and sync.id == 77
    assert sync_client.calls == async_client.calls
    assert kinds(sync_client) == ["start"] + ["chunk"] * expected + ["complete"]
    numbers = [int(c["parts"]["chunkNumber"][1]) for c in sync_client.calls if "parts" in c]
    assert numbers == list(range(expected))
    sent = b"".join(c["parts"]["chunk"][1] for c in sync_client.calls if "parts" in c)
    assert sent == path.read_bytes()
    assert sync_client.calls[-1]["json"]["totalChunks"] == expected


async def test_completion_uses_the_chunks_sent_not_the_servers_suggestion(tmp_path):
    """Covers REQ-003-05: the start response says totalChunks=1, but 3 chunks were sent.

    Completing with the suggestion silently truncates the file on the server, so the count
    must come from what was actually uploaded.
    """
    path = file_of(tmp_path, 10)
    client = Recorder(start_body={"uploadId": "up-1", "chunkSize": 100000000, "totalChunks": 1})

    FilesResource(client).upload_chunked(path, chunk_size=4)

    assert client.calls[-1]["json"]["totalChunks"] == 3


async def test_requests_use_the_server_field_names_and_session_id(tmp_path):
    """Covers REQ-003-05: camelCase bodies, the session's uploadId, and the stored name."""
    path = file_of(tmp_path, 6)
    sync_client, async_client = Recorder(), AsyncRecorder()

    FilesResource(sync_client).upload_chunked(path, chunk_size=4, name="renamed.bin")
    await AsyncFilesResource(async_client).upload_chunked(path, chunk_size=4, name="renamed.bin")

    start, first, _, complete = sync_client.calls
    assert (start["method"], start["path"]) == ("POST", f"{BASE}/start")
    assert start["json"] == {"fileName": "renamed.bin", "fileSize": 6}
    assert first["path"] == f"{BASE}/chunk"
    assert first["parts"]["uploadId"][1] == "up-1"
    assert first["parts"]["chunk"][0] == "chunk_0"
    assert complete["path"] == f"{BASE}/complete"
    assert complete["json"] == {"uploadId": "up-1", "fileName": "renamed.bin", "totalChunks": 2}
    assert sync_client.calls == async_client.calls


async def test_description_goes_in_metadata_with_a_matching_name(tmp_path):
    """Covers REQ-003-18: the description is a metadata object on completion, never top level."""
    path = file_of(tmp_path, 6)
    sync_client, async_client = Recorder(), AsyncRecorder()

    FilesResource(sync_client).upload_chunked(path, chunk_size=4, description="Ünïcode ✓")
    await AsyncFilesResource(async_client).upload_chunked(
        path, chunk_size=4, description="Ünïcode ✓"
    )

    complete = sync_client.calls[-1]["json"]
    assert "description" not in complete
    assert complete["metadata"] == {"name": "big.bin", "description": "Ünïcode ✓", "properties": {}}
    assert sync_client.calls == async_client.calls


async def test_a_missing_start_session_id_falls_back_to_a_generated_one(tmp_path):
    """Covers REQ-003-06: with no uploadId in the start response a UUID is used throughout."""
    path = file_of(tmp_path, 6)
    for body in ({}, {"chunkSize": 1}, None):
        client = Recorder(start_body=body if body is not None else [])
        FilesResource(client).upload_chunked(path, chunk_size=4)
        ids = {c["parts"]["uploadId"][1] for c in client.calls if "parts" in c}
        ids.add(client.calls[-1]["json"]["uploadId"])
        assert len(ids) == 1
        (generated,) = ids
        assert len(generated) == 36 and generated != "up-1"


async def test_a_failed_chunk_cancels_the_session_and_reraises_in_sync_and_async(tmp_path):
    """Covers REQ-003-05: a failing step cancels the session; the original error is raised."""
    path = file_of(tmp_path, 10)
    sync_client, async_client = Recorder(fail_on_chunk=1), AsyncRecorder(fail_on_chunk=1)

    with pytest.raises(APIError, match="chunk rejected"):
        FilesResource(sync_client).upload_chunked(path, chunk_size=4)
    with pytest.raises(APIError, match="chunk rejected"):
        await AsyncFilesResource(async_client).upload_chunked(path, chunk_size=4)

    assert kinds(sync_client) == ["start", "chunk", "chunk", "up-1"]
    assert sync_client.calls[-1]["method"] == "DELETE"
    assert sync_client.calls[-1]["path"] == f"{BASE}/up-1"
    assert sync_client.calls == async_client.calls


async def test_a_failing_cancel_does_not_hide_the_original_error(tmp_path):
    """Covers BEH-003-03: if cancellation also fails, the upload failure is what is raised."""
    path = file_of(tmp_path, 10)
    sync_client = Recorder(fail_on_chunk=0, fail_cancel=True)
    async_client = AsyncRecorder(fail_on_chunk=0, fail_cancel=True)

    with pytest.raises(APIError, match="chunk rejected"):
        FilesResource(sync_client).upload_chunked(path, chunk_size=4)
    with pytest.raises(APIError, match="chunk rejected"):
        await AsyncFilesResource(async_client).upload_chunked(path, chunk_size=4)


async def test_an_empty_file_sends_no_chunks(tmp_path):
    """Covers REQ-003-05: nothing to send means start then complete with zero chunks."""
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    client = Recorder()

    FilesResource(client).upload_chunked(path, chunk_size=4)

    assert kinds(client) == ["start", "complete"]
    assert client.calls[-1]["json"]["totalChunks"] == 0


@pytest.mark.parametrize("chunk", [0, -5])
async def test_a_non_positive_chunk_size_is_rejected_before_any_request(tmp_path, chunk):
    """Covers REQ-003-05: a chunk size below 1 raises ValueError and contacts nothing."""
    path = file_of(tmp_path, 10)
    sync_client, async_client = Recorder(), AsyncRecorder()

    with pytest.raises(ValueError, match="chunk_size"):
        FilesResource(sync_client).upload_chunked(path, chunk_size=chunk)
    with pytest.raises(ValueError, match="chunk_size"):
        await AsyncFilesResource(async_client).upload_chunked(path, chunk_size=chunk)

    assert sync_client.calls == [] and async_client.calls == []


async def test_a_missing_file_is_rejected_before_any_request(tmp_path):
    """Covers BEH-003-01: a missing path raises ValueError before the session starts."""
    client = Recorder()

    with pytest.raises(ValueError, match="does not exist"):
        FilesResource(client).upload_chunked(tmp_path / "nope.bin")

    assert client.calls == []
