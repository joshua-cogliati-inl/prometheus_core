"""Route the generated Nexus client's HTTP calls through the storage client.

Generated operations call ``client.get_httpx_client().request(...)`` and
``client.get_async_httpx_client().request(...)``. The httpx clients built here route those
calls through the storage client's own ``_request``, so authentication, token refresh,
retries and the mapping of HTTP errors to storage exceptions stay in one place. Because
``_request`` raises on non-2xx statuses, generated operations only ever parse successes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from deeplynx_nexus_client import Client

if TYPE_CHECKING:
    from .async_client import AsyncStorageClient
    from .client import StorageClient


class _RoutedClient(httpx.Client):
    """An httpx client whose requests are sent by ``StorageClient._request``."""

    def __init__(self, owner: "StorageClient"):
        super().__init__()
        self._owner = owner

    def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        return self._owner._request(str(method).upper(), str(url), **kwargs)


class _RoutedAsyncClient(httpx.AsyncClient):
    """An httpx async client whose requests are sent by ``AsyncStorageClient._request``."""

    def __init__(self, owner: "AsyncStorageClient"):
        super().__init__()
        self._owner = owner

    async def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        return await self._owner._request(str(method).upper(), str(url), **kwargs)


def generated_client(owner: Any, *, asynchronous: bool = False) -> Any:
    """Return a generated ``Client`` whose requests go through ``owner._request``.

    The result is cached on ``owner`` (one per sync or async owner).
    """
    cached = getattr(owner, "_generated_client", None)
    if cached is not None:
        return cached
    client = Client(base_url=owner.config.base_url)
    if asynchronous:
        client.set_async_httpx_client(_RoutedAsyncClient(owner))
    else:
        client.set_httpx_client(_RoutedClient(owner))
    owner._generated_client = client
    return client
