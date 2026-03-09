# MCP-Jira Server (Manual Baseline)
# A lightweight FastAPI application simulating an MCP server that connects
# AI assistants to Jira. Exposes a health endpoint for deployment verification
# and functional endpoints that simulate Jira operations.
#

import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------
MCP_API_VERSION = os.getenv("MCP_API_VERSION", "v1")
SERVICE_NAME = "MCP-Jira"
STARTUP_TIME = time.time()

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title=SERVICE_NAME,
    description="MCP server for Jira integration (simulated)",
    version=MCP_API_VERSION,
)


# ---------------------------------------------------------------------------
# Health endpoint — used by CI/CD pipeline and evaluation scripts to confirm
# the server is running and responsive. Returns service metadata.
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
# Used to validate that all required fields are present (correctness metric).
# ---------------------------------------------------------------------------
@app.get("/manifest")
def manifest():
    return {
        "name": SERVICE_NAME,
        "version": MCP_API_VERSION,
        "description": "MCP server enabling AI assistants to interact with Jira",
        "endpoints": [
            {
                "path": "/create_ticket",
                "method": "GET",
                "description": "Create a new Jira ticket",
                "parameters": ["project", "summary", "description", "priority"],
            },
            {
                "path": "/get_ticket",
                "method": "GET",
                "description": "Retrieve a Jira ticket by key",
                "parameters": ["ticket_key"],
            },
            {
                "path": "/list_tickets",
                "method": "GET",
                "description": "List tickets in a project",
                "parameters": ["project", "status", "max_results"],
            },
        ],
        "required_env_vars": [
            {"name": "MCP_API_VERSION", "required": False, "default": "v1"},
        ],
        "health_check": "/health",
    }


# ---------------------------------------------------------------------------
# Functional endpoints — simulate Jira operations. These return realistic
# response structures so that test_endpoints.py can validate them.
# ---------------------------------------------------------------------------
@app.get("/create_ticket")
def create_ticket(
    project: str = Query(..., description="Jira project key (e.g. PROJ)"),
    summary: str = Query(..., description="Ticket summary/title"),
    description: str = Query("", description="Ticket description"),
    priority: str = Query("Medium", description="Priority: Low, Medium, High, Critical"),
):
    if priority not in ("Low", "Medium", "High", "Critical"):
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

    # Simulate ticket creation with a deterministic fake key
    ticket_key = f"{project}-{abs(hash(summary)) % 9000 + 1000}"
    return {
        "status": "success",
        "ticket": {
            "key": ticket_key,
            "project": project,
            "summary": summary,
            "description": description,
            "priority": priority,
            "created": datetime.now(timezone.utc).isoformat(),
        },
        "api_version": MCP_API_VERSION,
    }


@app.get("/get_ticket")
def get_ticket(
    ticket_key: str = Query(..., description="Jira ticket key (e.g. PROJ-1234)"),
):
    return {
        "status": "success",
        "ticket": {
            "key": ticket_key,
            "summary": f"Simulated ticket {ticket_key}",
            "description": "This is a simulated Jira ticket for thesis evaluation.",
            "priority": "Medium",
            "status": "Open",
            "created": datetime.now(timezone.utc).isoformat(),
        },
        "api_version": MCP_API_VERSION,
    }


@app.get("/list_tickets")
def list_tickets(
    project: str = Query(..., description="Jira project key"),
    status: str = Query("Open", description="Filter by status"),
    max_results: int = Query(10, description="Maximum results to return", ge=1, le=50),
):
    # Simulate a list of tickets
    tickets = [
        {
            "key": f"{project}-{i}",
            "summary": f"Simulated ticket #{i}",
            "status": status,
            "priority": "Medium",
        }
        for i in range(1, min(max_results, 5) + 1)
    ]
    return {
        "status": "success",
        "project": project,
        "total": len(tickets),
        "tickets": tickets,
        "api_version": MCP_API_VERSION,
    }