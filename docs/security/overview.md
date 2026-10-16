# Security

## Identity and access

Use Azure `DefaultAzureCredential` with a supported managed identity or workload identity in
deployed environments. Do not log or persist access tokens, credential object representations, or
raw SDK exceptions. Grant only read access to the subscription inventory needed by the application
and verify effective role assignments. The adapter does not provision identities or change
resource permissions.

## Query and data scope

The adapter accepts a subscription UUID and validated exact resource-type and location filters. It
builds a fixed KQL query, projects only resource ID, name, type, and location, and does not expose
tags, arbitrary properties, or caller-supplied query text. These constraints reduce query and data
exposure; they do not make inventory public. Resource identifiers and names reveal environment
topology and should be access-controlled and handled according to the cloud inventory's data
classification.

The common models hide subscription scope, resource IDs, names, and cursors from ordinary
representations. Explicit serialization, app logs, traces, memory dumps, and transport diagnostics
can still disclose them. Avoid logging full result pages or opaque continuation tokens. Provider
errors are mapped to generic categories rather than returning the raw Azure response message.

Use verified TLS and restrict outbound access according to deployment policy. Partial or delayed
results are not proof of resource absence or compliance.

## Vulnerability reporting

Use the repository's [private security reporting process](../../SECURITY.md).
