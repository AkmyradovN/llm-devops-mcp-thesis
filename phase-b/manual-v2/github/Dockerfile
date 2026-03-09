FROM python:3.10-slim
LABEL project="mcp-thesis" service="MCP-GitHub" baseline="manual-v2"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# ARG below busts cache at this layer when BUILD_TS changes, ensuring fresh app code
ARG BUILD_TS=0
COPY app.py .

EXPOSE 8000
ENV MCP_API_VERSION=v2
ENV MCP_SERVER_ENV=production
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]