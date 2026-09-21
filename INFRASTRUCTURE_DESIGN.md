# Infrastructure and Sandbox Design

## Node records

Node records are stored in the platform database under `nodes`, keyed by a generated node ID. A record contains `name`, `provider`, `connection_type` (`local`, `ssh`, or `agent`), address fields, port, username, enabled state, authentication method, encrypted credential references, last test state, detected capabilities, and timestamps. Secret material is encrypted at rest with the platform keyring and is redacted from logs and backups.

A normal public web page is never treated as an SSH endpoint. `agent` nodes require a documented authenticated API or agent protocol. Unsupported connection types remain visible as `UNSUPPORTED` and cannot receive workloads.

## Execution boundary

The local node is only selected automatically when the control-plane and worker runtime are on the same machine. Sandboxed workloads use Docker when available, with non-root execution, resource limits, restricted mounts, separate working directories, and bounded logs. If Docker is unavailable, the system reports `NEEDS SETUP`; it does not silently run untrusted uploads directly on the host.

## Migration and recovery

Existing bot records remain valid when sandbox mode changes. A mode transition changes only future starts; running bots require an explicit restart/migration action. Cipher Vault snapshots include node assignments and sanitized manifests but never plaintext node credentials or bot tokens.

## Host support

The application logic is host-independent. Railway, Render, and similar services can use the local node only within their own runtime and should not be presented as permanent VPS capacity. Persistent VPS nodes require Docker or an authenticated agent/SSH interface and explicit administrator confirmation for installation or destructive operations.
