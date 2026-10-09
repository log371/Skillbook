# Security scope

This is a single-operator demonstration, not a certified secure AI platform. Report issues
through GitHub private vulnerability reporting if enabled; do not publish credentials.

Trusted: host administrator, signing workstation/key, Python runtime, Ollama, operator-owned
release directory and public key. Untrusted: HTTP input, context documents, model proposals,
unsigned/removable-media bundles. Signed text is not executable code.

The Python policy, not the model or an injection detector, enforces document capabilities.
No arbitrary filesystem path, shell, network tool or plugin entry point is implemented.
The API key grants all operations exposed by this demo; this is not tenant isolation.
Run one worker. Runtime state and operator update state must have different write permissions.

The audit chain detects edits against its retained contents, but truncation/full rewriting
requires an independently stored head checkpoint. Logs are not immutable. Operators must
manage retention and disk capacity. Log failure refuses the request. Stop the service and
preserve evidence if startup audit verification fails.

Signatures do not sanitize malicious instructions or excessive permissions signed by a
trusted operator. Review permission changes before signing. Pin/verify models separately.
Local inference does not by itself establish network isolation; enforce it on the host.
