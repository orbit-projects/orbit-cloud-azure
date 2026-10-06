# ADR 0001: Azure Resource Graph as the inventory backend

**Status:** Accepted for pre-alpha implementation  
**Date:** 2026-10-06

## Context

The provider adapter implements the shared `orbit-cloud` read-only inventory protocol. It must map common filters and pagination into the provider API without importing provider behavior into the capability package, granting write access, or returning arbitrary metadata that can contain sensitive values.

## Decision

Use the asynchronous ResourceGraphClient and Azure Identity AsyncTokenCredential. V1 scopes one Azure subscription UUID. Construct a fixed KQL query from validated provider type and location identifiers; never accept arbitrary KQL from the shared contract. Project only resource id, name, type, and location, and order by id for cursor paging. Close both the client and credential.

## Consequences

Provider indexing, query semantics, permissions, result freshness, partial coverage, and pagination remain provider-specific. The common page model does not imply complete or strongly consistent inventory. Fake-client tests cover translation and lifecycle; live cloud behavior is a separate release gate.

## Validation required

Before stable support, validate the least-privilege policy, SDK/API compatibility, page-token behavior, partial-result handling, cancellation, timeouts, and shutdown in a dedicated non-production cloud environment. Record the tested service, SDK, and Python versions.
