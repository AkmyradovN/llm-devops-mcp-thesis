# MCP-Jira Server (Manual Baseline)
# Builds a minimal container running the MCP-Jira FastAPI application.
# Includes a HEALTHCHECK directive so Docker can report container health
# and the CI/CD pipeline can verify deployment success.

FROM python:3.10-slim

# Metadata
LABEL project="mcp-thesis"
LABEL service="MCP-Jira"
LABEL baseline="manual"

WORKDIR /app

# Install curl for health checks (needed by HEALTHCHECK directive)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (separate layer for Docker cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Expose the application port
EXPOSE 8000

# Health check: Docker will poll this every 30s to determine container health
# Retries 3 times with 10s between retries before marking unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]