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

"""Async files resource."""

from pathlib import Path
from typing import Any, Optional
from ..models.file import FileMetadata
from ..exceptions import StorageClientError
from ..nexus_client import generated_client, operation
from ..resources.files import build_upload_request, parse_file_record
from .base import AsyncBaseResource


class AsyncFilesResource(AsyncBaseResource):
    """Handles async operations related to file storage and retrieval."""

    def _generated(self) -> Any:
        return generated_client(self._client, asynchronous=True)

    def _scope(self) -> tuple:
        config = self._client.config
        return config.organization_id, config.project_id

    async def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file to storage asynchronously."""
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")

        file_name = name or file_path.name

        organization_id, project_id = self._scope()
        with open(file_path, "rb") as f:
            method, path, request = build_upload_request(organization_id, project_id, f, file_name)
            response = await self._client._request(method, path, **request)

        return parse_file_record(response.json())

    async def upload_chunked(
        self,
        file_path: Path,
        chunk_size: int = 5 * 1024 * 1024,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> FileMetadata:
        """Upload a large file in chunks asynchronously."""
        from ..utils.streaming import AsyncChunkedUploader

        uploader = AsyncChunkedUploader(self._client, chunk_size)
        return await uploader.upload(file_path, name, description)

    async def get(self, file_id: int) -> FileMetadata:
        """Get file metadata by ID.

        Files are records, so this reads the record.

        Raises:
            ItemNotFoundError: If file doesn't exist
        """
        organization_id, project_id = self._scope()
        response = await operation("record", "api_get_a_record").asyncio_detailed(
            organization_id, project_id, file_id, client=self._generated()
        )
        if response.parsed is None or not hasattr(response.parsed, "id"):
            raise StorageClientError(
                f"Unexpected response to get file (HTTP {int(response.status_code)})"
            )
        return FileMetadata.from_generated(response.parsed)

    async def download(self, file_id: int, output_path: Path) -> None:
        """Download a file to local storage.

        Args:
            file_id: File identifier (record ID from upload)
            output_path: Where to save the downloaded file

        Raises:
            ItemNotFoundError: If file doesn't exist

        Example:
            ```python
            await client.files.download(123, Path("downloaded.csv"))
            ```
        """
        organization_id, project_id = self._scope()
        response = await operation("file", "api_download_file").asyncio_detailed(
            organization_id, project_id, file_id, client=self._generated()
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)

    async def delete(self, file_id: int) -> None:
        """Delete a file.

        Raises:
            ItemNotFoundError: If file doesn't exist
        """
        organization_id, project_id = self._scope()
        await operation("file", "api_delete_file").asyncio_detailed(
            organization_id, project_id, file_id, client=self._generated()
        )

    def _parse_file_metadata(self, data: dict) -> FileMetadata:
        """Parse API response data into FileMetadata model."""
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
