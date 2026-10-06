# orbit-cloud-azure: architecture

`orbit-cloud-azure` implements the provider-neutral [`orbit-cloud`](https://github.com/orbit-projects/orbit-cloud) asynchronous read-only inventory contract. This adapter owns its vendor SDK, identity integration, query translation, pagination mapping, safe error mapping, and SDK client lifecycle. The capability package does not depend on the vendor SDK.

Only normalized identifiers, type, display name, location, and bounded labels are returned. Raw vendor response documents are intentionally excluded because they may contain sensitive values and provider-specific schema.
