# MCP-Jira Server v2
# Changes from v1: endpoints prefixed with /v2/, health returns api_status/environment fields


import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

MCP_API_VERSION = os.environ["MCP_API_VERSION"]  # v2: required, no default
MCP_SERVER_ENV = os.getenv("MCP_SERVER_ENV", "staging")
SERVICE_NAME = "MCP-Jira"
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
        "description": "MCP server enabling AI assistants to interact with Jira",
        "endpoints": [
            {"path": "/v2/create_ticket", "method": "GET", "parameters": ["project", "summary", "description", "priority"]},
            {"path": "/v2/get_ticket", "method": "GET", "parameters": ["ticket_key"]},
            {"path": "/v2/list_tickets", "method": "GET", "parameters": ["project", "status", "max_results"]},
        ],
        "required_env_vars": [
            {"name": "MCP_API_VERSION", "required": True},
            {"name": "MCP_SERVER_ENV", "required": False, "default": "staging"},
        ],
        "health_check": "/health",
    }


@app.get("/v2/create_ticket")
def create_ticket(
    project: str = Query(...), summary: str = Query(...),
    description: str = Query(""), priority: str = Query("Medium"),
):
    if priority not in ("Low", "Medium", "High", "Critical"):
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")
    ticket_key = f"{project}-{abs(hash(summary)) % 9000 + 1000}"
    return {
        "status": "success",
        "ticket": {"key": ticket_key, "project": project, "summary": summary, "description": description, "priority": priority, "created": datetime.now(timezone.utc).isoformat()},
        "api_version": MCP_API_VERSION,
        "environment": MCP_SERVER_ENV,
    }


@app.get("/v2/get_ticket")
def get_ticket(ticket_key: str = Query(...)):
    return {
        "status": "success",
        "ticket": {"key": ticket_key, "summary": f"Simulated ticket {ticket_key}", "status": "Open", "priority": "Medium"},
        "api_version": MCP_API_VERSION,
        "environment": MCP_SERVER_ENV,
    }


@app.get("/v2/list_tickets")
def list_tickets(project: str = Query(...), status: str = Query("Open"), max_results: int = Query(10, ge=1, le=50)):
    tickets = [{"key": f"{project}-{i}", "summary": f"Simulated ticket #{i}", "status": status} for i in range(1, min(max_results, 5) + 1)]
    return {"status": "success", "project": project, "total": len(tickets), "tickets": tickets, "api_version": MCP_API_VERSION, "environment": MCP_SERVER_ENV}