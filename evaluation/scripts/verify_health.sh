#!/usr/bin/env bash
# =============================================================================
# verify_health.sh — Health endpoint verification with retry and timing
# =============================================================================
# Usage:
#   bash verify_health.sh <EC2_IP> [jira_port] [github_port] [max_retries] [retry_interval]
#
# Example:
#   bash verify_health.sh 52.59.191.104 80 81 12 5
#
# Outputs: pass/fail for each server + response time in milliseconds
# =============================================================================

set -uo pipefail

EC2_IP="${1:?Usage: verify_health.sh <EC2_IP> [jira_port] [github_port]}"
JIRA_PORT="${2:-80}"
GITHUB_PORT="${3:-81}"
MAX_RETRIES="${4:-12}"
RETRY_INTERVAL="${5:-5}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

JIRA_PASS=0
GITHUB_PASS=0
JIRA_RESPONSE_MS=0
GITHUB_RESPONSE_MS=0

echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  Health Check Verification${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"

check_health() {
    local name="$1"
    local port="$2"
    local expected_service="$3"

    echo -e "\n${YELLOW}Checking $name on port $port...${NC}"

    for i in $(seq 1 "$MAX_RETRIES"); do
        # Capture HTTP code and response time
        RESPONSE=$(curl -sf -w "\n%{http_code}\n%{time_total}" \
            "http://${EC2_IP}:${port}/health" 2>/dev/null || echo -e "\n000\n0")

        # Parse response
        BODY=$(echo "$RESPONSE" | head -1)
        HTTP_CODE=$(echo "$RESPONSE" | tail -2 | head -1)
        TIME_TOTAL=$(echo "$RESPONSE" | tail -1)

        if [ "$HTTP_CODE" = "200" ]; then
            # Validate response body
            if echo "$BODY" | grep -q "\"status\"" && echo "$BODY" | grep -q "\"ok\""; then
                RESPONSE_MS=$(echo "$TIME_TOTAL * 1000" | bc 2>/dev/null || echo "0")
                echo -e "  ${GREEN}✓ $name HEALTHY${NC}"
                echo "    Response: $BODY"
                echo "    Time:     ${RESPONSE_MS}ms"

                # Check service name
                if echo "$BODY" | grep -q "$expected_service"; then
                    echo -e "    Service:  ${GREEN}$expected_service (correct)${NC}"
                else
                    echo -e "    Service:  ${RED}expected $expected_service (MISMATCH)${NC}"
                fi

                echo "$RESPONSE_MS"
                return 0
            fi
        fi

        echo "  Attempt $i/$MAX_RETRIES — HTTP $HTTP_CODE, retrying in ${RETRY_INTERVAL}s..."
        sleep "$RETRY_INTERVAL"
    done

    echo -e "  ${RED}✗ $name FAILED after $MAX_RETRIES attempts${NC}"
    echo "0"
    return 1
}

# Run checks
JIRA_MS=$(check_health "MCP-Jira" "$JIRA_PORT" "MCP-Jira") && JIRA_PASS=1
GITHUB_MS=$(check_health "MCP-GitHub" "$GITHUB_PORT" "MCP-GitHub") && GITHUB_PASS=1

# Summary
echo -e "\n${YELLOW}═══════════════════════════════════════════════════${NC}"
echo "  HEALTH CHECK SUMMARY"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo "  MCP-Jira:   $([ $JIRA_PASS -eq 1 ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
echo "  MCP-GitHub: $([ $GITHUB_PASS -eq 1 ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
echo ""
echo ">> For results.csv:"
echo "   health_endpoint_pass = $(( JIRA_PASS & GITHUB_PASS ))"

# Exit code: 0 if both pass, 1 if any fail
[ $JIRA_PASS -eq 1 ] && [ $GITHUB_PASS -eq 1 ]