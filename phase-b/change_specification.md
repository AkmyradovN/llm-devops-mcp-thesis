# Phase B Change Specification — API Version v1 → v2
# =========================================================================
# This document defines the exact changes required for the adaptability test.
# Both manual and LLM approaches must produce configurations that satisfy
# all requirements below.
#
# The scenario simulates a real-world API version bump where:
#   - Endpoint paths change (adding /v2/ prefix)
#   - A new required environment variable is introduced
#   - Response schemas gain new fields
#   - The health endpoint must report the new version
# =========================================================================

## Change Summary

| Component         | v1 (Phase A)                     | v2 (Phase B)                              |
|-------------------|----------------------------------|-------------------------------------------|
| MCP_API_VERSION   | "v1" (optional, default)         | "v2" (required, no default)               |
| Health response   | version: "v1"                    | version: "v2", api_status: "stable"       |
| Jira endpoints    | /create_ticket, /get_ticket      | /v2/create_ticket, /v2/get_ticket         |
| GitHub endpoints  | /create_issue, /get_issue        | /v2/create_issue, /v2/get_issue           |
| Manifest          | Lists v1 paths                   | Lists v2 paths, adds "api_version": "v2"  |
| New env var       | —                                | MCP_SERVER_ENV (required: "production")   |
| Docker            | No env requirement               | ENV MCP_API_VERSION=v2 in Dockerfile      |
| Terraform         | No change                        | Pass MCP_SERVER_ENV to user-data script   |

## Detailed Requirements

### 1. Application Changes (app.py)
- All functional endpoint paths must be prefixed with /v2/
  - Jira:   /v2/create_ticket, /v2/get_ticket, /v2/list_tickets
  - GitHub: /v2/create_issue, /v2/get_issue, /v2/list_issues
- /health endpoint adds: "api_status": "stable" to its response
- /manifest endpoint updates paths to /v2/... versions
- New environment variable: MCP_SERVER_ENV (read with os.getenv, default "staging")
- All responses include "api_version": "v2" and "environment": <MCP_SERVER_ENV value>

### 2. Dockerfile Changes
- Add: ENV MCP_API_VERSION=v2
- Add: ENV MCP_SERVER_ENV=production

### 3. Terraform Changes (minimal)
- No structural changes required
- The user-data script should export MCP_SERVER_ENV=production

### 4. CI/CD Changes
- Functional test endpoints update to /v2/ paths
- Health check validates "api_status": "stable" in response

## Verification Checklist (Phase B)
- [ ] /health returns {"status":"ok", "version":"v2", "api_status":"stable", ...}
- [ ] /v2/create_ticket (Jira) or /v2/create_issue (GitHub) returns success
- [ ] Old /create_ticket and /create_issue paths return 404 or are removed
- [ ] MCP_SERVER_ENV is read and included in responses
- [ ] Manifest lists /v2/ paths