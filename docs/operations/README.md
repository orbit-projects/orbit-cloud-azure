# Operations

`AzureCloudInventory` executes read-only Azure Resource Graph requests against one subscription.
It builds a fixed KQL query from validated resource-type and location filters, projects only
`id`, `name`, `type`, and `location`, and orders by ID for predictable pagination. It does not
accept arbitrary KQL, return tags/properties, or perform resource mutations.

## Identity and scope

`CloudInventoryQuery.scope` must be a subscription UUID. The adapter passes only that subscription
to Resource Graph. The default identity path uses async `DefaultAzureCredential`, which resolves
an explicitly supported local or managed identity source. Inject a credential factory only when
the application owns a specific supported identity. Grant the runtime identity only read access
to the selected subscription and verify effective role assignment before rollout.

## Filters and pagination

Resource types and locations are inserted into a fixed query only after common-contract identifier
validation; arbitrary query syntax is not accepted. Keep the returned `next_page_token` opaque and
use it only with the same subscription, filters, and page size. Azure's result truncation indicator
without a continuation token maps to `partial=True`. Preserve partial status; an incomplete page
must not be presented as a complete inventory.

## Timeouts and lifecycle

The credential and Resource Graph client are created lazily on the first valid request and shared
across calls. `max_concurrency` bounds active requests, and `request_timeout_seconds` is enforced
around the complete query and any retry delay. Retry allows at most `retry_total` retries (default
3) and uses full jitter over exponential intervals, starting at
`retry_initial_backoff_seconds` (default 0.5 seconds) and capped at `retry_max_backoff_seconds`
(default 10 seconds). The Azure SDK honors a server-provided `Retry-After` value; the overall
request deadline still bounds the complete operation. Cancellation propagates. `aclose()` rejects
new work, drains active queries, then closes both client and credential. A client or credential
close failure is aggregated into one sanitized error after both close attempts. If cleanup fails,
new requests stay blocked and a later `aclose()` retries only resources that did not close
successfully. Call it during application shutdown and set a bounded shutdown deadline.

## Operational validation

In a dedicated non-production subscription, validate role assignments, query filter behavior,
ordering and continuation, provider truncation, result ceilings, request throttling, timeout,
cancellation, credential refresh, and cleanup when one resource close fails. Fake-client checks do
not verify live Azure Resource Graph semantics or subscription-wide completeness.
