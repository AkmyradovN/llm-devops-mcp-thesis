# MCP-GitHub Server v2 - same structure as v1 with all endpoints at /v2/ prefix

import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

MCP_API_VERSION = os.environ["MCP_API_VERSION"]
MCP_SERVER_ENV = os.getenv("MCP_SERVER_ENV", "staging")
SERVICE_NAME = "MCP-GitHub"
STARTUP_TIME = time.time()

app = FastAPI(title=SERVICE_NAME, version=MCP_API_VERSION)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": MCP_API_VERSION,
        "api_status": "stable",
        "environment": MCP_SERVER_ENV,
        "uptime_seconds": round(time.time() - STARTUP_TIME, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/manifest")
def manifest():
    return {
        "name": SERVICE_NAME,
        "version": MCP_API_VERSION,
        "api_version": "v2",
        "description": "MCP server enabling AI assistants to manage GitHub Issues",
        "endpoints": [
            {"path": "/v2/create_issue", "method": "GET", "parameters": ["owner", "repo", "title", "body", "labels"]},
            {"path": "/v2/get_issue", "method": "GET", "parameters": ["owner", "repo", "issue_number"]},
            {"path": "/v2/list_issues", "method": "GET", "parameters": ["owner", "repo", "state", "max_results"]},
        ],
        "required_env_vars": [
            {"name": "MCP_API_VERSION", "required": True},
            {"name": "MCP_SERVER_ENV", "required": False, "default": "staging"},
        ],
        "health_check": "/health",
    }


@app.get("/v2/create_issue")
def create_issue(
    owner: str = Query(...), repo: str = Query(...), title: str = Query(...),
    body: str = Query(""), labels: str = Query(""),
):
    issue_number = abs(hash(title)) % 900 + 100
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
    return {
        "status": "success",
        "issue": {"number": issue_number, "owner": owner, "repo": repo, "title": title, "body": body, "labels": label_list, "state": "open", "url": f"https://github.com/{owner}/{repo}/issues/{issue_number}"},
        "api_version": MCP_API_VERSION,
        "environment": MCP_SERVER_ENV,
    }


@app.get("/v2/get_issue")
def get_issue(owner: str = Query(...), repo: str = Query(...), issue_number: int = Query(..., ge=1)):
    return {
        "status": "success",
        "issue": {"number": issue_number, "owner": owner, "repo": repo, "title": f"Simulated issue #{issue_number}", "state": "open"},
        "api_version": MCP_API_VERSION,
        "environment": MCP_SERVER_ENV,
    }


@app.get("/v2/list_issues")
def list_issues(owner: str = Query(...), repo: str = Query(...), state: str = Query("open"), max_results: int = Query(10, ge=1, le=50)):
    if state not in ("open", "closed", "all"):
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")
    issues = [{"number": i, "title": f"Simulated issue #{i}", "state": "open"} for i in range(1, min(max_results, 5) + 1)]
    return {"status": "success", "owner": owner, "repo": repo, "total": len(issues), "issues": issues, "api_version": MCP_API_VERSION, "environment": MCP_SERVER_ENV}