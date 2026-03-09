# Correctness Checklist — MCP-GitHub Server
# =========================================================================
# Used to evaluate both manual baseline and LLM-generated artefacts.
# Each item scores 1 (pass) or 0 (fail). Total checks: 25.
# correctness_score = max(0, 1 - (total_failures / 25))
#
# Evaluator: check each item against the generated files and mark [x] or [ ].
# =========================================================================

## Terraform Configuration (8 checks)

- [ ] **T1** — AWS provider block present with `region` variable reference
- [ ] **T2** — EC2 instance resource defined with `instance_type` set to `t2.micro`
- [ ] **T3** — AMI references Ubuntu 22.04 (either via data source or correct AMI ID for eu-central-1)
- [ ] **T4** — Security group allows inbound on port 22 (SSH)
- [ ] **T5** — Security group allows inbound on port 80 (MCP-Jira)
- [ ] **T6** — Security group allows inbound on port 81 (MCP-GitHub)
- [ ] **T7** — Key pair reference present (`key_name` variable or resource)
- [ ] **T8** — Output block exports `public_ip` of the EC2 instance

## Dockerfile — MCP-GitHub (6 checks)

- [ ] **D1** — Base image is `python:3.10-slim` (or compatible Python 3.10+ slim variant)
- [ ] **D2** — `requirements.txt` copied and `pip install` executed
- [ ] **D3** — `app.py` copied into the container
- [ ] **D4** — Port 8000 exposed (`EXPOSE 8000`)
- [ ] **D5** — Entrypoint runs uvicorn on host `0.0.0.0` port `8000`
- [ ] **D6** — HEALTHCHECK directive present, targeting `/health`

## CI/CD Workflow (6 checks)

- [ ] **C1** — Trigger configured on push to the correct branch
- [ ] **C2** — SSH key setup step present (writes key from secret, sets permissions)
- [ ] **C3** — Docker build command executed on EC2 for MCP-GitHub image
- [ ] **C4** — Container run command maps port 81 to container port 8000
- [ ] **C5** — Health check step present that verifies HTTP 200 from port 81 `/health`
- [ ] **C6** — Pipeline fails (non-zero exit) if health check does not pass

## MCP Application — GitHub (5 checks)

- [ ] **A1** — `/health` endpoint returns JSON with `"status": "ok"` and `"service": "MCP-GitHub"`
- [ ] **A2** — `/manifest` endpoint returns JSON listing available endpoints
- [ ] **A3** — `/create_issue` endpoint accepts `owner`, `repo`, and `title` parameters, returns `"status": "success"`
- [ ] **A4** — `MCP_API_VERSION` environment variable is read and included in responses
- [ ] **A5** — Application runs via uvicorn (FastAPI/ASGI server)

---

## Scoring

| Category      | Checks | Passed | Failed |
|---------------|--------|--------|--------|
| Terraform     | 8      |        |        |
| Dockerfile    | 6      |        |        |
| CI/CD         | 6      |        |        |
| Application   | 5      |        |        |
| **Total**     | **25** |        |        |

**correctness_score** = max(0, 1 − (total_failed / 25)) = ___

**manual_edits_lines** (LLM only) = ___