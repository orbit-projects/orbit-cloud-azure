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
import random
from types import SimpleNamespace
from typing import Any

import pytest
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.policies import AsyncRetryPolicy
from orbit_cloud import CloudInventoryQuery, CloudOperationError

from orbit_cloud_azure import AzureCloudInventory, AzureCloudInventoryConfig
from orbit_cloud_azure.inventory import _build_retry_policy, _default_client_factory

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
        self.close_attempts = 0

    async def resources(self, query: Any, **kwargs: Any) -> Any:
        self.request = query
        self.timeout = kwargs.get("timeout")
        if self.failure is not None:
            raise self.failure
        return self.response

    async def close(self) -> None:
        self.close_attempts += 1
        self.closed = True


def make_provider(client: FakeClient, credential: FakeCredential) -> AzureCloudInventory:
    return AzureCloudInventory(
        credential_factory=lambda: credential,
        client_factory=lambda _credential, _config: client,
    )


def test_retry_policy_is_bounded_and_uses_full_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure finite retries and randomize exponential delays within a strict cap."""
    config = AzureCloudInventoryConfig()
    policy = _build_retry_policy(config)
    observed: list[tuple[float, float]] = []

    def select_upper_bound(lower: float, upper: float) -> float:
        """Capture jitter limits and select the upper bound deterministically."""
        observed.append((lower, upper))
        return upper

    monkeypatch.setattr(random, "uniform", select_upper_bound)

    def retry_settings(error_count: int) -> dict[str, object]:
        """Return the Azure Core retry state for a number of consecutive errors."""
        return {
            "history": [object()] * error_count,
            "backoff": policy.backoff_factor,
            "max_backoff": policy.backoff_max,
        }

    assert isinstance(policy, AsyncRetryPolicy)
    assert policy.total_retries == 3
    assert policy.backoff_factor == 0.5
    assert policy.backoff_max == 10.0
    assert policy.get_backoff_time(retry_settings(1)) == 0.5
    assert policy.get_backoff_time(retry_settings(5)) == 8.0
    assert policy.get_backoff_time(retry_settings(8)) == 10.0
    assert observed == [(0.0, 0.5), (0.0, 8.0), (0.0, 10.0)]


def test_default_client_factory_installs_the_configured_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass configured retry policy into the actual Azure Resource Graph client."""
    options: dict[str, Any] = {}

    def capture_client(credential: Any, **kwargs: Any) -> FakeClient:
        """Capture SDK configuration without creating a network connection."""
        del credential
        options.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("orbit_cloud_azure.inventory.ResourceGraphClient", capture_client)
    config = AzureCloudInventoryConfig(retry_total=5)
    _default_client_factory(FakeCredential(), config)

    policy = options["retry_policy"]
    assert isinstance(policy, AsyncRetryPolicy)
    assert policy.total_retries == 5
    assert policy.backoff_factor == 0.5
    assert policy.backoff_max == 10.0


@pytest.mark.parametrize(
    "configuration",
    [
        {"retry_total": -1},
        {"retry_total": 11},
        {"retry_initial_backoff_seconds": 11.0},
        {"retry_initial_backoff_seconds": 5.0, "retry_max_backoff_seconds": 4.0},
    ],
)
def test_retry_configuration_rejects_invalid_bounds(configuration: dict[str, object]) -> None:
    """Reject attempt counts and backoff intervals outside their documented bounds."""
    with pytest.raises(ValueError):
        AzureCloudInventoryConfig(**configuration)


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


@pytest.mark.asyncio
async def test_failed_close_can_be_retried_without_reusing_closed_provider() -> None:
    class RetryableCloseClient(FakeClient):
        async def close(self) -> None:
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise RuntimeError("temporary close failure")
            self.closed = True

    client = RetryableCloseClient()
    credential = FakeCredential()
    provider = make_provider(client, credential)
    await provider.list_resources(CloudInventoryQuery(scope=SUBSCRIPTION))

    with pytest.raises(CloudOperationError, match="could not all be closed"):
        await provider.aclose()
    with pytest.raises(CloudOperationError, match="provider is closed"):
        await provider.list_resources(CloudInventoryQuery(scope=SUBSCRIPTION))

    await provider.aclose()
    assert client.close_attempts == 2
    assert client.closed
    assert credential.closed


@pytest.mark.asyncio
async def test_credential_close_failure_retries_only_the_credential() -> None:
    class RetryableCloseCredential(FakeCredential):
        def __init__(self) -> None:
            super().__init__()
            self.close_attempts = 0

        async def close(self) -> None:
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise RuntimeError("temporary credential close failure")
            self.closed = True

    client = FakeClient()
    credential = RetryableCloseCredential()
    provider = make_provider(client, credential)
    await provider.list_resources(CloudInventoryQuery(scope=SUBSCRIPTION))

    with pytest.raises(CloudOperationError, match="could not all be closed"):
        await provider.aclose()
    await provider.aclose()

    assert client.close_attempts == 1
    assert credential.close_attempts == 2
    assert credential.closed
