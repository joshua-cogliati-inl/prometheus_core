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

"""Streaming utilities for large file uploads.

Chunked uploads use the generated Nexus client's operations: start a session, send each chunk,
then complete (or cancel) it. Two server rules shape the code:

- ``totalChunks`` in the completion request MUST be the number of chunks actually sent. The
  start response suggests a count based on the server's own chunk size, but the server accepts
  smaller chunks, and completing with the suggested count (for example 1) silently truncates
  the file to that many chunks while still answering 200.
- The description is not a top-level field; it travels in ``metadata`` like a plain upload's.
"""

import io
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from ..exceptions import StorageClientError
from ..models.file import FileMetadata
from ..nexus_client import models, operation, types

if TYPE_CHECKING:
    from ..async_client import AsyncStorageClient
    from ..client import StorageClient

Request = Tuple[str, str, Dict[str, Any]]


def _request(operation_name: str, *args: Any, **kwargs: Any) -> Request:
    """``(method, path, request kwargs)`` from a generated file operation's request builder."""
    built = operation("file", operation_name)._get_kwargs(*args, **kwargs)
    method, path = built.pop("method"), built.pop("url")
    return str(method).upper(), str(path), built


def start_request(org: int, project: int, file_name: str, file_size: int) -> Request:
    body = models().FileUploadInitRequestDto(file_name=file_name, file_size=file_size)
    return _request("api_start_file_upload", org, project, body=body)


def chunk_request(org: int, project: int, upload_id: str, number: int, data: bytes) -> Request:
    chunk = types().File(payload=io.BytesIO(data), file_name=f"chunk_{number}")
    body = models().ApiUploadFileChunkBody(chunk=chunk, upload_id=upload_id, chunk_number=number)
    return _request("api_upload_file_chunk", org, project, body=body)


def complete_request(
    org: int,
    project: int,
    upload_id: str,
    file_name: str,
    description: Optional[str],
    total_chunks: int,
) -> Request:
    generated = models()
    fields: Dict[str, Any] = {}
    if description:
        # Name, Description and Properties are all required by the server; Name repeats the
        # stored name, as for a plain upload.
        fields["metadata"] = generated.CreateRecordFileUploadRequestDto(
            name=file_name,
            description=description,
            properties=generated.JsonObject.from_dict({}),
        )
    body = generated.FileUploadCompleteRequestDto(
        upload_id=upload_id, file_name=file_name, total_chunks=total_chunks, **fields
    )
    return _request("api_complete_file_upload", org, project, body=body)


def cancel_request(org: int, project: int, upload_id: str) -> Request:
    return _request("api_cancel_file_upload", org, project, upload_id)


def session_id(response_body: Any) -> str:
    """The upload session ID from a start response (``uploadId``); a fresh UUID if it has none."""
    upload_id = response_body.get("uploadId") if isinstance(response_body, dict) else None
    return str(upload_id or uuid.uuid4())


def check_upload(file_path: Path, chunk_size: int) -> None:
    if not file_path.exists():
        raise ValueError(f"File does not exist: {file_path}")
    if chunk_size < 1:
        raise ValueError("chunk_size must be 1 or greater")


def parse_completed(response_body: Any) -> FileMetadata:
    from ..resources.files import parse_file_record

    if not isinstance(response_body, dict):
        raise StorageClientError("Unexpected response to complete upload")
    return parse_file_record(response_body)


class ChunkedUploader:
    """Handles chunked file uploads for large files."""

    def __init__(self, client: "StorageClient", chunk_size: int = 5 * 1024 * 1024):
        """Initialize chunked uploader.

        Args:
            client: Storage client instance
            chunk_size: Size of each chunk in bytes (default 5MB). The server accepts chunks
                smaller than the one it suggests.
        """
        self.client = client
        self.chunk_size = chunk_size

    def _ids(self) -> Tuple[int, int]:
        config = self.client.config
        return config.organization_id, config.project_id

    def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file in chunks.

        Args:
            file_path: Path to the file to upload
            name: Optional custom name
            description: Optional description

        Returns:
            File metadata

        Raises:
            ValueError: If the file doesn't exist or ``chunk_size`` is less than 1
        """
        check_upload(file_path, self.chunk_size)
        file_name = name or file_path.name
        upload_id = self._start_upload(file_name, file_path.stat().st_size)

        try:
            sent = 0
            with open(file_path, "rb") as f:
                while True:
                    data = f.read(self.chunk_size)
                    if not data:
                        break
                    self._upload_chunk(upload_id, sent, data)
                    sent += 1
            return self._complete_upload(upload_id, file_name, description, sent)
        except Exception:
            # Best effort: the original failure is what the caller needs to see
            try:
                self._cancel_upload(upload_id)
            except Exception:
                pass
            raise

    def _start_upload(self, file_name: str, file_size: int) -> str:
        method, path, request = start_request(*self._ids(), file_name, file_size)
        return session_id(self.client._request(method, path, **request).json())

    def _upload_chunk(self, upload_id: str, chunk_num: int, chunk_data: bytes) -> None:
        method, path, request = chunk_request(*self._ids(), upload_id, chunk_num, chunk_data)
        self.client._request(method, path, **request)

    def _complete_upload(
        self, upload_id: str, file_name: str, description: Optional[str], total_chunks: int
    ) -> FileMetadata:
        method, path, request = complete_request(
            *self._ids(), upload_id, file_name, description, total_chunks
        )
        return parse_completed(self.client._request(method, path, **request).json())

    def _cancel_upload(self, upload_id: str) -> None:
        method, path, request = cancel_request(*self._ids(), upload_id)
        self.client._request(method, path, **request)


class AsyncChunkedUploader:
    """Async version of chunked file uploader."""

    def __init__(self, client: "AsyncStorageClient", chunk_size: int = 5 * 1024 * 1024):
        """Initialize async chunked uploader.

        Args:
            client: Async storage client instance
            chunk_size: Size of each chunk in bytes (default 5MB)
        """
        self.client = client
        self.chunk_size = chunk_size

    def _ids(self) -> Tuple[int, int]:
        config = self.client.config
        return config.organization_id, config.project_id

    async def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file in chunks asynchronously. See ``ChunkedUploader.upload``."""
        check_upload(file_path, self.chunk_size)
        file_name = name or file_path.name
        upload_id = await self._start_upload(file_name, file_path.stat().st_size)

        try:
            sent = 0
            with open(file_path, "rb") as f:
                while True:
                    data = f.read(self.chunk_size)
                    if not data:
                        break
                    await self._upload_chunk(upload_id, sent, data)
                    sent += 1
            return await self._complete_upload(upload_id, file_name, description, sent)
        except Exception:
            try:
                await self._cancel_upload(upload_id)
            except Exception:
                pass
            raise

    async def _start_upload(self, file_name: str, file_size: int) -> str:
        method, path, request = start_request(*self._ids(), file_name, file_size)
        return session_id((await self.client._request(method, path, **request)).json())

    async def _upload_chunk(self, upload_id: str, chunk_num: int, chunk_data: bytes) -> None:
        method, path, request = chunk_request(*self._ids(), upload_id, chunk_num, chunk_data)
        await self.client._request(method, path, **request)

    async def _complete_upload(
        self, upload_id: str, file_name: str, description: Optional[str], total_chunks: int
    ) -> FileMetadata:
        method, path, request = complete_request(
            *self._ids(), upload_id, file_name, description, total_chunks
        )
        return parse_completed((await self.client._request(method, path, **request)).json())

    async def _cancel_upload(self, upload_id: str) -> None:
        method, path, request = cancel_request(*self._ids(), upload_id)
        await self.client._request(method, path, **request)
