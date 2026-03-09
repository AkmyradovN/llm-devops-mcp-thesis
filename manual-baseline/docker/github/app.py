# app.py — MCP-GitHub Server (Manual Baseline)
# =============================================================================
# A lightweight FastAPI application simulating an MCP server that connects
# AI assistants to GitHub Issues. Exposes a health endpoint for deployment
# verification and functional endpoints that simulate GitHub operations.
#
# Part of the manual baseline for the MSc thesis:
# "LLM-Assisted DevOps for Automated Deployment and Management of MCP
#  Servers on Cloud Platforms"
# =============================================================================

import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------
MCP_API_VERSION = os.getenv("MCP_API_VERSION", "v1")
SERVICE_NAME = "MCP-GitHub"
STARTUP_TIME = time.time()

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title=SERVICE_NAME,
    description="MCP server for GitHub Issues integration (simulated)",
    version=MCP_API_VERSION,
)


# ---------------------------------------------------------------------------
# Health endpoint — used by CI/CD pipeline and evaluation scripts to confirm
# the server is running and responsive.
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": MCP_API_VERSION,
        "uptime_seconds": round(time.time() - STARTUP_TIME, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# MCP manifest endpoint — describes the capabilities of this MCP server.
# ---------------------------------------------------------------------------
@app.get("/manifest")
def manifest():
    return {
        "name": SERVICE_NAME,
        "version": MCP_API_VERSION,
        "description": "MCP server enabling AI assistants to manage GitHub Issues",
        "endpoints": [
            {
                "path": "/create_issue",
                "method": "GET",
                "description": "Create a new GitHub issue",
                "parameters": ["owner", "repo", "title", "body", "labels"],
            },
            {
                "path": "/get_issue",
                "method": "GET",
                "description": "Retrieve a GitHub issue by number",
                "parameters": ["owner", "repo", "issue_number"],
            },
            {
                "path": "/list_issues",
                "method": "GET",
                "description": "List issues in a repository",
                "parameters": ["owner", "repo", "state", "max_results"],
            },
        ],
        "required_env_vars": [
            {"name": "MCP_API_VERSION", "required": False, "default": "v1"},
        ],
        "health_check": "/health",
    }


# ---------------------------------------------------------------------------
# Functional endpoints — simulate GitHub Issues operations.
# ---------------------------------------------------------------------------
@app.get("/create_issue")
def create_issue(
    owner: str = Query(..., description="Repository owner (e.g. AkmyradovN)"),
    repo: str = Query(..., description="Repository name"),
    title: str = Query(..., description="Issue title"),
    body: str = Query("", description="Issue body/description"),
    labels: str = Query("", description="Comma-separated labels (e.g. bug,enhancement)"),
):
    # Simulate issue creation with a deterministic fake number
    issue_number = abs(hash(title)) % 900 + 100
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []

    return {
        "status": "success",
        "issue": {
            "number": issue_number,
            "owner": owner,
            "repo": repo,
            "title": title,
            "body": body,
            "labels": label_list,
            "state": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "url": f"https://github.com/{owner}/{repo}/issues/{issue_number}",
        },
        "api_version": MCP_API_VERSION,
    }


@app.get("/get_issue")
def get_issue(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    issue_number: int = Query(..., description="Issue number", ge=1),
):
    return {
        "status": "success",
        "issue": {
            "number": issue_number,
            "owner": owner,
            "repo": repo,
            "title": f"Simulated issue #{issue_number}",
            "body": "This is a simulated GitHub issue for thesis evaluation.",
            "labels": ["simulation"],
            "state": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "url": f"https://github.com/{owner}/{repo}/issues/{issue_number}",
        },
        "api_version": MCP_API_VERSION,
    }


@app.get("/list_issues")
def list_issues(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    state: str = Query("open", description="Filter by state: open, closed, all"),
    max_results: int = Query(10, description="Maximum results to return", ge=1, le=50),
):
    if state not in ("open", "closed", "all"):
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")

    issues = [
        {
            "number": i,
            "title": f"Simulated issue #{i}",
            "state": "open" if state in ("open", "all") else "closed",
            "labels": ["simulation"],
            "url": f"https://github.com/{owner}/{repo}/issues/{i}",
        }
        for i in range(1, min(max_results, 5) + 1)
    ]
    return {
        "status": "success",
        "owner": owner,
        "repo": repo,
        "total": len(issues),
        "issues": issues,
        "api_version": MCP_API_VERSION,
    }