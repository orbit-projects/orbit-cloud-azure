# orbit-cloud-azure: security

This adapter is read-only and uses the configured cloud SDK identity chain. Grant only the provider permissions needed for inventory queries. Keep credentials in a secret manager or workload identity; never put credentials in query scopes, page cursors, resource metadata, logs, or error messages.

The adapter does not configure cloud identities, issue credentials, or certify account policy. Verify effective permissions and network policy in the target cloud environment before deployment.
