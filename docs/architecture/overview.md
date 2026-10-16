# Architecture

`orbit-cloud-azure` implements `orbit_cloud.CloudInventoryProvider` with the async Azure Resource
Graph client and Azure Identity credential. The adapter satisfies the provider-neutral
[`orbit-cloud`](https://github.com/orbit-projects/orbit-cloud) contract for one subscription.

```text
CloudInventoryQuery
  ├── scope → one validated subscription UUID
  ├── resource_types / locations → fixed KQL equality filters
  ├── page size / cursor → QueryRequestOptions
  └── no user-authored KQL
        ↓
Azure Resource Graph
        ↓
fixed projection: id, name, type, location; ordered by id
        ↓
CloudInventoryPage + opaque cursor + truncation/partial signal
```

The adapter owns Azure credential construction, Resource Graph client configuration, query
translation, continuation mapping, timeout/concurrency behavior, safe error categories, and
client/credential cleanup. Client and credential creation are lazy; `aclose()` drains in-flight
queries before closing both resources.

The adapter uses `result_truncated` to mark `partial=True` when the provider reports truncation but
returns no continuation token. It intentionally excludes tags and raw properties. Resource Graph
scope, permissions, provider limits, and continuation behavior remain Azure-specific; the common
contract does not claim complete or immediate inventory. The fake-client tests make no live Azure
service validation claim.
