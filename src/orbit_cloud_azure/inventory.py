# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Async, read-only Azure Resource Graph adapter."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.identity.aio import DefaultAzureCredential
from azure.mgmt.resourcegraph.aio import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from orbit_cloud import (
    CloudConfigurationError,
    CloudInventoryPage,
    CloudInventoryQuery,
    CloudOperationError,
    CloudResource,
)

from orbit_cloud_azure.config import AzureCloudInventoryConfig


class _AzureGraphClient(Protocol):
    async def resources(self, query: QueryRequest, **kwargs: Any) -> Any:
        """Execute a bounded Azure Resource Graph query."""

    async def close(self) -> None:
        """Close the Azure Resource Graph client."""


CredentialFactory = Callable[[], AsyncTokenCredential]
ClientFactory = Callable[[AsyncTokenCredential, AzureCloudInventoryConfig], _AzureGraphClient]


class AzureCloudInventory:
    """List resources from one Azure subscription using Azure Resource Graph."""

    def __init__(
        self,
        config: AzureCloudInventoryConfig | None = None,
        *,
        credential_factory: CredentialFactory | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.config = config or AzureCloudInventoryConfig()
        self._credential_factory = credential_factory or DefaultAzureCredential
        self._client_factory = client_factory or _default_client_factory
        self._credential: AsyncTokenCredential | None = None
        self._client: _AzureGraphClient | None = None
        self._client_lock = asyncio.Lock()
        self._condition = asyncio.Condition()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._active = 0
        self._closing = False
        self._closed = False

    async def _get_client(self) -> _AzureGraphClient:
        async with self._client_lock:
            if self._client is None:
                credential = self._credential_factory()
                try:
                    client = self._client_factory(credential, self.config)
                except BaseException:
                    await credential.close()
                    raise
                self._credential = credential
                self._client = client
            return self._client

    @asynccontextmanager
    async def _use_client(self) -> AsyncIterator[_AzureGraphClient]:
        async with self._condition:
            if self._closing or self._closed:
                raise CloudOperationError("closed", "Azure inventory provider is closed.")
            self._active += 1
        try:
            async with self._semaphore:
                yield await self._get_client()
        finally:
            async with self._condition:
                self._active -= 1
                self._condition.notify_all()

    async def list_resources(self, query: CloudInventoryQuery) -> CloudInventoryPage:
        """Run a parameterized, read-only Resource Graph query for one subscription."""
        try:
            subscription_id = str(uuid.UUID(query.scope))
        except (ValueError, AttributeError):
            raise CloudConfigurationError("scope must be an Azure subscription UUID.") from None

        request = QueryRequest(
            query=_build_query(query),
            subscriptions=[subscription_id],
            options=QueryRequestOptions(
                top=query.page_size,
                skip_token=query.page_token,
                result_format="objectArray",
                allow_partial_scopes=False,
            ),
        )
        try:
            async with asyncio.timeout(self.config.request_timeout_seconds):
                async with self._use_client() as client:
                    response = await client.resources(
                        request,
                        timeout=self.config.request_timeout_seconds,
                    )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise CloudOperationError(
                "timeout", "Azure inventory request timed out.", retryable=True
            ) from None
        except HttpResponseError as exc:
            raise _map_azure_error(exc) from None
        except (ServiceRequestError, ServiceResponseError):
            raise CloudOperationError(
                "provider-unavailable",
                "Azure inventory is temporarily unavailable.",
                retryable=True,
            ) from None
        except CloudOperationError:
            raise
        except Exception:
            raise CloudOperationError(
                "provider-failure", "Azure inventory request failed."
            ) from None

        try:
            rows = response.data
            if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
                raise ValueError("invalid rows")
            resources = tuple(
                CloudResource(
                    provider="azure",
                    resource_id=_required_string(row, "id"),
                    resource_type=_required_string(row, "type"),
                    name=_optional_string(row, "name"),
                    location=_optional_string(row, "location"),
                )
                for row in rows
            )
            token = response.skip_token or None
            truncated = str(response.result_truncated).lower() == "true"
            return CloudInventoryPage(
                resources=resources,
                next_page_token=token,
                partial=truncated and token is None,
            )
        except (AttributeError, TypeError, ValueError):
            raise CloudOperationError(
                "invalid-response", "Azure inventory returned invalid resource metadata."
            ) from None

    async def aclose(self) -> None:
        """Drain active queries and close both owned SDK client and identity credential."""
        async with self._condition:
            if self._closed:
                return
            if self._closing:
                await self._condition.wait_for(lambda: self._closed or not self._closing)
                if self._closed:
                    return
            self._closing = True
            try:
                await self._condition.wait_for(lambda: self._active == 0)
            except BaseException:
                self._closing = False
                self._condition.notify_all()
                raise
        close_failed = False
        if self._client is not None:
            try:
                await self._client.close()
            except asyncio.CancelledError:
                async with self._condition:
                    self._closing = False
                    self._condition.notify_all()
                raise
            except Exception:
                close_failed = True
        if self._credential is not None:
            try:
                await self._credential.close()
            except asyncio.CancelledError:
                async with self._condition:
                    self._closing = False
                    self._condition.notify_all()
                raise
            except Exception:
                close_failed = True
        async with self._condition:
            self._closed = True
            self._closing = False
            self._condition.notify_all()
        if close_failed:
            raise CloudOperationError(
                "close-failed", "Azure SDK resources could not all be closed."
            ) from None


def _default_client_factory(
    credential: AsyncTokenCredential, config: AzureCloudInventoryConfig
) -> _AzureGraphClient:
    return cast(
        _AzureGraphClient,
        ResourceGraphClient(
            credential,
            connection_timeout=config.connect_timeout_seconds,
            read_timeout=config.request_timeout_seconds,
            retry_total=3,
        ),
    )


def _build_query(query: CloudInventoryQuery) -> str:
    parts = ["Resources"]
    if query.resource_types:
        values = ", ".join(f"'{value}'" for value in query.resource_types)
        parts.append(f"| where type in ({values})")
    if query.locations:
        values = ", ".join(f"'{value}'" for value in query.locations)
        parts.append(f"| where location in ({values})")
    parts.extend(("| project id, name, type, location", "| order by id asc"))
    return " ".join(parts)


def _required_string(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("invalid resource field")
    return value


def _optional_string(row: Mapping[str, Any], key: str) -> str | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("invalid resource field")
    return value


def _map_azure_error(exc: HttpResponseError) -> CloudOperationError:
    status = exc.status_code
    if status == 401 or status == 403:
        return CloudOperationError("permission-denied", "Azure denied the inventory request.")
    if status == 429:
        return CloudOperationError(
            "throttled", "Azure limited the inventory request.", retryable=True
        )
    if status is not None and status >= 500:
        return CloudOperationError(
            "provider-unavailable", "Azure inventory is temporarily unavailable.", retryable=True
        )
    if status == 400:
        return CloudOperationError("invalid-query", "Azure rejected the inventory query.")
    return CloudOperationError("provider-failure", "Azure inventory request failed.")


__all__ = ["AzureCloudInventory"]
