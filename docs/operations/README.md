# orbit-cloud-azure: operations

This package performs read-only cloud resource inventory using the provider's inventory API. It owns one lazily created asynchronous SDK client and closes it through `aclose()`; call that method during application shutdown. Request timeouts and in-flight concurrency are bounded. Request cancellation is propagated by the asynchronous SDK.

Use least-privilege inventory permissions, workload identity where available, TLS verification, and a secret manager for credentials. Provider inventory can be eventually consistent, permission-filtered, or incomplete. See the repository README for provider-specific setup requirements and limits.
