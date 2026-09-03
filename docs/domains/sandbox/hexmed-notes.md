# Hexmed Stack Integration Notes

This document records the configuration, dependency discovery, and isolation validation for `hexmed-stack`.

## 1. Port Mapping Analysis

Scanning `.env*` configurations within `hexmed-stack` revealed the following dependencies:

| Port | Service | Sandbox Architecture |
|---|---|---|
| `5432` | PostgreSQL (`pacsdb`) | Runs as disposable service in isolated pod (`postgres:14`). |
| `6379` | Redis (`REDIS_URL`, `CELERY_BROKER_URL`) | Runs as disposable service in isolated pod (`redis:7-alpine`). |
| `8080` | DCM4CHEE ARC 5 DICOM server | Host/infrastructure service. Does not exist in isolated pod; candidate for `mode = "attached"` or test stubs. |
| `8008` | PACS server API | Service under test (binds loopback inside pod). |
| `4041` | Portal backend API | Service under test (binds loopback inside pod). |
| `3000` / `5173` | OHIF Viewer / Vite frontend | Dev servers inside pod. |

## 2. Project Profile Configuration

Saved in `/home/v/Data/Projects/hexmed-stack/.agent-sandbox.toml`:

```toml
[sandbox]
mode = "isolated"

[services.postgres]
image = "postgres:14"
port  = 5432

[services.redis]
image = "redis:7-alpine"
port  = 6379

[network]
allow = ["registry.npmjs.org", "repo.maven.apache.org", "pypi.org", "files.pythonhosted.org"]

[proxy]
java = true
```

## 3. Orca Lifecycle Recipe

- Created `./scripts/orca-vm/create.sh` and `./scripts/orca-vm/destroy.sh` pointing to `agent-sandbox` recipes via the shared shim template.
- Declared in `orca.yaml`.
- Verified via `orca vm recipe doctor agent-sandbox --repo-path /home/v/Data/Projects/hexmed-stack --json` (status: `ok: true`).
