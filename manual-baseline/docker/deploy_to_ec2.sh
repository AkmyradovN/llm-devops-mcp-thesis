#!/usr/bin/env bash
# Deploy both MCP servers to EC2 (Manual Baseline)
# Usage:
#   bash deploy_to_ec2.sh <EC2_PUBLIC_IP> <PATH_TO_PEM>
#
# Example:
#   bash deploy_to_ec2.sh 3.123.45.67 manual-baseline/terraform/personalTestEC2.pem
#
# This script:
#   1. Copies both Docker directories to the EC2 instance
#   2. Builds both Docker images on the instance
#   3. Stops any existing containers
#   4. Starts fresh containers (Jira on port 80, GitHub on port 81)
#   5. Waits for health checks to pass
#   6. Reports deployment time

set -euo pipefail

# ---- Arguments ----
EC2_IP="${1:?Usage: deploy_to_ec2.sh <EC2_IP> <PEM_PATH>}"
PEM_PATH="${2:?Usage: deploy_to_ec2.sh <EC2_IP> <PEM_PATH>}"
EC2_USER="ubuntu"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# ---- Paths (relative to repo root) ----
JIRA_DIR="manual-baseline/docker/jira"
GITHUB_DIR="manual-baseline/docker/github"

# ---- Colours ----
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  MCP Server Deployment — Manual Baseline${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo ""

# Record start time
DEPLOY_START=$(date +%s)

# ---- Step 1: Copy files to EC2 ----
echo -e "${YELLOW}[1/5] Copying Docker files to EC2...${NC}"
scp $SSH_OPTS -i "$PEM_PATH" -r "$JIRA_DIR" "${EC2_USER}@${EC2_IP}:/home/ubuntu/jira"
scp $SSH_OPTS -i "$PEM_PATH" -r "$GITHUB_DIR" "${EC2_USER}@${EC2_IP}:/home/ubuntu/github"
echo -e "${GREEN}  ✓ Files copied${NC}"

# ---- Step 2: Build images on EC2 ----
echo -e "${YELLOW}[2/5] Building Docker images on EC2...${NC}"
ssh $SSH_OPTS -i "$PEM_PATH" "${EC2_USER}@${EC2_IP}" << 'REMOTE_BUILD'
set -e
cd /home/ubuntu/jira && docker build -t mcp-jira . > /dev/null 2>&1
cd /home/ubuntu/github && docker build -t mcp-github . > /dev/null 2>&1
echo "Build complete"
REMOTE_BUILD
echo -e "${GREEN}  ✓ Images built${NC}"

# ---- Step 3: Stop existing containers ----
echo -e "${YELLOW}[3/5] Stopping existing containers...${NC}"
ssh $SSH_OPTS -i "$PEM_PATH" "${EC2_USER}@${EC2_IP}" << 'REMOTE_STOP'
docker stop mcp-jira 2>/dev/null || true
docker rm mcp-jira 2>/dev/null || true
docker stop mcp-github 2>/dev/null || true
docker rm mcp-github 2>/dev/null || true
REMOTE_STOP
echo -e "${GREEN}  ✓ Old containers cleared${NC}"

# ---- Step 4: Start new containers ----
echo -e "${YELLOW}[4/5] Starting containers...${NC}"
ssh $SSH_OPTS -i "$PEM_PATH" "${EC2_USER}@${EC2_IP}" << 'REMOTE_START'
docker run -d --name mcp-jira -p 80:8000 --restart unless-stopped mcp-jira
docker run -d --name mcp-github -p 81:8000 --restart unless-stopped mcp-github
REMOTE_START
echo -e "${GREEN}  ✓ Containers started (Jira: port 80, GitHub: port 81)${NC}"

# ---- Step 5: Health checks with retry ----
echo -e "${YELLOW}[5/5] Waiting for health checks...${NC}"

check_health() {
    local name="$1"
    local port="$2"
    local max_retries=12
    local retry=0

    while [ $retry -lt $max_retries ]; do
        HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "http://${EC2_IP}:${port}/health" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            RESPONSE=$(curl -sf "http://${EC2_IP}:${port}/health" 2>/dev/null)
            echo -e "${GREEN}  ✓ ${name} healthy (port ${port}): ${RESPONSE}${NC}"
            return 0
        fi
        retry=$((retry + 1))
        echo "    Waiting for ${name}... (attempt ${retry}/${max_retries})"
        sleep 5
    done
    echo -e "${RED}  ✗ ${name} FAILED to become healthy after ${max_retries} attempts${NC}"
    return 1
}

JIRA_OK=0
GITHUB_OK=0

check_health "MCP-Jira" 80 && JIRA_OK=1
check_health "MCP-GitHub" 81 && GITHUB_OK=1

# ---- Report ----
DEPLOY_END=$(date +%s)
DEPLOY_DURATION=$((DEPLOY_END - DEPLOY_START))

echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  Deployment Summary${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo "  EC2 IP:          ${EC2_IP}"
echo "  MCP-Jira:        http://${EC2_IP}:80/health  $([ $JIRA_OK -eq 1 ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
echo "  MCP-GitHub:      http://${EC2_IP}:81/health  $([ $GITHUB_OK -eq 1 ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
echo "  Deploy time:     ${DEPLOY_DURATION} seconds"
echo "  Timestamp:       $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Exit with failure if either server didn't come up
if [ $JIRA_OK -eq 0 ] || [ $GITHUB_OK -eq 0 ]; then
    echo -e "${RED}Deployment completed with failures.${NC}"
    exit 1
fi

echo -e "${GREEN}Deployment successful.${NC}"
echo ""
echo "Record this in results.csv:"
echo "  t_pipeline_secs = ${DEPLOY_DURATION}"