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
"""Azure query translation, safe errors, cancellation, and client lifecycle tests."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from azure.core.exceptions import HttpResponseError
from orbit_cloud import CloudInventoryQuery, CloudOperationError

from orbit_cloud_azure import AzureCloudInventory

SUBSCRIPTION = "12345678-1234-5678-1234-567812345678"


class FakeCredential:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self) -> None:
        self.request: Any = None
        self.timeout: float | None = None
        self.response = SimpleNamespace(
            data=[
                {
                    "id": (
                        "/subscriptions/12345678-1234-5678-1234-567812345678/"
                        "resourceGroups/app/providers/Microsoft.Compute/virtualMachines/web"
                    ),
                    "name": "web",
                    "type": "Microsoft.Compute/virtualMachines",
                    "location": "eastus",
                    "tags": {"secret-like": "not-selected"},
                }
            ],
            skip_token="opaque-azure-token",
            result_truncated="true",
        )
        self.failure: Exception | None = None
        self.closed = False

    async def resources(self, query: Any, **kwargs: Any) -> Any:
        self.request = query
        self.timeout = kwargs.get("timeout")
        if self.failure is not None:
            raise self.failure
        return self.response

    async def close(self) -> None:
        self.closed = True


def make_provider(client: FakeClient, credential: FakeCredential) -> AzureCloudInventory:
    return AzureCloudInventory(
        credential_factory=lambda: credential,
        client_factory=lambda _credential, _config: client,
    )


@pytest.mark.asyncio
async def test_inventory_builds_safe_query_and_returns_page() -> None:
    client = FakeClient()
    credential = FakeCredential()
    provider = make_provider(client, credential)

    page = await provider.list_resources(
        CloudInventoryQuery(
            scope=SUBSCRIPTION,
            resource_types=("Microsoft.Compute/virtualMachines",),
            locations=("eastus", "westus2"),
            page_size=25,
            page_token="prior-token",
        )
    )

    assert client.request.subscriptions == [SUBSCRIPTION]
    assert client.request.query == (
        "Resources | where type in ('Microsoft.Compute/virtualMachines') "
        "| where location in ('eastus', 'westus2') "
        "| project id, name, type, location | order by id asc"
    )
    assert client.request.options.top == 25
    assert client.request.options.skip_token == "prior-token"
    assert client.timeout == 30
    assert page.resources[0].provider == "azure"
    assert page.resources[0].name == "web"
    assert page.resources[0].labels == {}
    assert page.next_page_token == "opaque-azure-token"
    assert page.partial is False
    assert "opaque-azure-token" not in repr(page)
    await provider.aclose()
    await provider.aclose()
    assert client.closed
    assert credential.closed


@pytest.mark.asyncio
async def test_rejects_invalid_scope_without_network_call() -> None:
    client = FakeClient()
    credential = FakeCredential()
    provider = make_provider(client, credential)

    with pytest.raises(ValueError, match="subscription UUID"):
        await provider.list_resources(CloudInventoryQuery(scope="subscriptions/x; Resources"))

    assert client.request is None
    await provider.aclose()
    assert not credential.closed


@pytest.mark.asyncio
async def test_error_mapping_does_not_leak_provider_message() -> None:
    client = FakeClient()
    credential = FakeCredential()
    failure = HttpResponseError(message="secret provider endpoint and token")
    failure.status_code = 429
    client.failure = failure
    provider = make_provider(client, credential)

    with pytest.raises(CloudOperationError) as caught:
        await provider.list_resources(CloudInventoryQuery(scope=SUBSCRIPTION))

    assert caught.value.code == "throttled"
    assert caught.value.retryable is True
    assert "secret provider" not in str(caught.value)
    await provider.aclose()
    assert credential.closed


@pytest.mark.asyncio
async def test_timeout_and_cancellation_propagate() -> None:
    client = FakeClient()
    credential = FakeCredential()
    entered = asyncio.Event()

    class BlockingClient(FakeClient):
        async def resources(self, query: Any, **kwargs: Any) -> Any:
            self.request = query
            entered.set()
            await asyncio.Event().wait()

    client = BlockingClient()
    provider = make_provider(client, credential)
    task = asyncio.create_task(provider.list_resources(CloudInventoryQuery(scope=SUBSCRIPTION)))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await provider.aclose()
    assert client.closed
    assert credential.closed
