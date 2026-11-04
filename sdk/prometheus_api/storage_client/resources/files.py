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

"""Files resource for synchronous operations."""

import io
import json
from pathlib import Path
from typing import Any, BinaryIO, Dict, Optional, Tuple
from ..models.file import FileMetadata
from ..exceptions import StorageClientError
from ..nexus_client import generated_client, models, operation, types
from .base import BaseResource


def build_upload_request(
    organization_id: int,
    project_id: int,
    payload: BinaryIO,
    file_name: str,
    description: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """The file upload request as ``(method, path, request kwargs)``.

    Built from the generated ``api_upload_file`` operation and ``ApiUploadFileBody``: a
    multipart body whose ``file`` part carries ``file_name`` (the stored name). The upload route
    has no description field; a description travels in the optional ``metadata`` part, a JSON
    document whose ``Name``, ``Description`` and ``Properties`` are all required and whose keys
    are case-sensitive. ``Name`` repeats ``file_name`` so the two cannot disagree. Without a
    description there is no ``metadata`` part, and the server names the description after the file.
    No data source is sent, so the server uses the project default.
    """
    body = models().ApiUploadFileBody(file=types().File(payload=payload, file_name=file_name))
    if description:
        document = {"Name": file_name, "Description": description, "Properties": {}}
        body.metadata = types().File(
            payload=io.BytesIO(json.dumps(document).encode("utf-8")),
            file_name="metadata.json",
            mime_type="application/json",
        )
    request = operation("file", "api_upload_file")._get_kwargs(
        organization_id, project_id, body=body
    )
    method, path = request.pop("method"), request.pop("url")
    return str(method).upper(), str(path), request


def parse_file_record(data: Dict[str, Any]) -> FileMetadata:
    """File metadata from a record body, parsed through the generated ``RecordResponseDto``.

    The generated parser iterates ``tags`` and ``labels`` without a null check, so null lists
    are dropped first.
    """
    record = {k: v for k, v in data.items() if not (k in ("tags", "labels") and v is None)}
    return FileMetadata.from_generated(models().RecordResponseDto.from_dict(record))


class FilesResource(BaseResource):
    """Handles operations related to file storage and retrieval."""

    def _generated(self) -> Any:
        return generated_client(self._client)

    def _scope(self) -> tuple:
        config = self._client.config
        return config.organization_id, config.project_id

    def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file to storage.

        Args:
            file_path: Path to the file to upload
            name: Optional custom name (defaults to filename)
            description: Optional file description

        Returns:
            File metadata

        Example:
            ```python
            file_meta = client.files.upload(
                Path("data.csv"),
                description="Experiment results"
            )
            ```
        """
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")

        file_name = name or file_path.name

        organization_id, project_id = self._scope()
        with open(file_path, "rb") as f:
            method, path, request = build_upload_request(
                organization_id, project_id, f, file_name, description
            )
            response = self._client._request(method, path, **request)

        return parse_file_record(response.json())

    def upload_chunked(
        self,
        file_path: Path,
        chunk_size: int = 5 * 1024 * 1024,  # 5MB default
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> FileMetadata:
        """Upload a large file in chunks.

        Args:
            file_path: Path to the file to upload
            chunk_size: Size of each chunk in bytes
            name: Optional custom name
            description: Optional file description

        Returns:
            File metadata

        Example:
            ```python
            # Upload large file in 10MB chunks
            file_meta = client.files.upload_chunked(
                Path("large_data.zip"),
                chunk_size=10 * 1024 * 1024
            )
            ```
        """
        from ..utils.streaming import ChunkedUploader

        uploader = ChunkedUploader(self._client, chunk_size)
        return uploader.upload(file_path, name, description)

    def get(self, file_id: int) -> FileMetadata:
        """Get file metadata by ID.

        Files are records, so this reads the record.

        Raises:
            ItemNotFoundError: If file doesn't exist
        """
        organization_id, project_id = self._scope()
        response = operation("record", "api_get_a_record").sync_detailed(
            organization_id, project_id, file_id, client=self._generated()
        )
        if response.parsed is None or not hasattr(response.parsed, "id"):
            raise StorageClientError(
                f"Unexpected response to get file (HTTP {int(response.status_code)})"
            )
        return FileMetadata.from_generated(response.parsed)

    def download(self, file_id: int, output_path: Path) -> None:
        """Download a file to local storage.

        Args:
            file_id: File identifier (record ID from upload)
            output_path: Where to save the downloaded file

        Raises:
            ItemNotFoundError: If file doesn't exist

        Example:
            ```python
            client.files.download(123, Path("downloaded.csv"))
            ```
        """
        organization_id, project_id = self._scope()
        response = operation("file", "api_download_file").sync_detailed(
            organization_id, project_id, file_id, client=self._generated()
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)

    def delete(self, file_id: int) -> None:
        """Delete a file.

        Raises:
            ItemNotFoundError: If file doesn't exist
        """
        organization_id, project_id = self._scope()
        operation("file", "api_delete_file").sync_detailed(
            organization_id, project_id, file_id, client=self._generated()
        )

    def _parse_file_metadata(self, data: dict) -> FileMetadata:
        """Parse API response data into FileMetadata model.

        Args:
            data: Raw API response data

        Returns:
            Parsed FileMetadata object

        Note:
            DeepLynx API returns field names like 'name', 'fileType', 'uri'.
        """
        return FileMetadata(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            file_type=data.get("fileType"),
            size=data.get("fileSize"),
            uri=data.get("uri"),
            created_at=data.get("createdAt"),
            updated_at=data.get("lastUpdatedAt") or data.get("updatedAt"),
        )
