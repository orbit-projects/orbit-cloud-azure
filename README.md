# orbit-cloud-azure

Lists Azure resources from one subscription using asynchronous Azure Resource Graph and Azure Identity clients.

This is the `Azure Resource Graph `resources` query API` adapter for the provider-neutral [`orbit-cloud`](https://github.com/orbit-projects/orbit-cloud) capability. It performs **read-only inventory**. It never provisions, modifies, or deletes cloud resources.

**Status:** pre-alpha. Contract tests use fake SDK clients and need no cloud credentials. No hosted CI, live-provider, production, support, or release-readiness claim is implied.

## Install

```bash
python -m pip install orbit-cloud orbit-cloud-azure
```

## Use

```python
from orbit_cloud import CloudInventoryQuery
from orbit_cloud_azure import AzureCloudInventory

provider = AzureCloudInventory()
try:
    page = await provider.list_resources(
        CloudInventoryQuery(
        scope="12345678-1234-5678-1234-567812345678",
        resource_types=("Microsoft.Compute/virtualMachines",),
        locations=("eastus",),
        page_size=100,
    )
    )
    for resource in page.resources:
        print(resource.resource_type, resource.resource_id)
finally:
    await provider.aclose()
```

The provider owns its async client and closes it during `aclose()`. Calls are bounded by finite request timeouts and a configurable concurrency limit. Cancellation propagates through the asynchronous client. `CloudInventoryPage.next_page_token` is opaque and provider-specific; use it only with the same scope, filters, and page size, and do not log it.

## Provider setup and limits

The `scope` is a subscription UUID. `DefaultAzureCredential` selects an explicitly configured supported credential or workload identity; no default credentials are bundled. Grant the identity only read access to the required subscription scope.

Azure Resource Graph is subscription-scoped in this adapter. The package builds a fixed, parameter-safe query from validated resource-type and location filters; arbitrary KQL is not accepted. Results are ordered by resource ID for stable pagination. Provider truncation without a continuation token is reported as partial. Tags and raw properties are not returned.

Resource identifiers and names may be sensitive. Orbit deliberately omits raw provider payloads. Do not log resource IDs, scopes, or continuation tokens unless your data handling policy permits it.

## SDK choice

The official `azure-mgmt-resourcegraph` async client and `azure-identity` async credential are used. The adapter is network-I/O-bound; no separate Go/Rust runtime or SDK is included without a measured use case.

The Python adapter is the baseline implementation. Native language alternatives require contract conformance and representative evidence before they are recommended.

## Documentation and development

Read the [architecture](docs/architecture/overview.md), [operations](docs/operations/README.md), [security](docs/security/overview.md), and [development](docs/development/README.md) guides.

```bash
python -m pip install -e '.[dev]' build
pytest
ruff check src tests
ruff format --check src tests
mypy
python -m build
```

Live validation, when added, must be opt-in and use a dedicated non-production account, project, or subscription.

Licensed under Apache-2.0.
