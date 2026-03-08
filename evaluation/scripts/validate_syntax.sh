#!/usr/bin/env bash
# =============================================================================
# validate_syntax.sh — Automated syntax validation for generated artefacts
# =============================================================================
# Runs terraform validate, hadolint (Dockerfile linter), and yamllint on
# generated files. Outputs a total error count for the correctness metric.
#
# Usage:
#   bash validate_syntax.sh <terraform_dir> <docker_jira_dir> <docker_github_dir> [ci_yaml_path]
#
# Example:
#   bash validate_syntax.sh \
#     llm-assisted/generated/run001/ \
#     llm-assisted/generated/run001/jira/ \
#     llm-assisted/generated/run001/github/ \
#     llm-assisted/generated/run001/deploy.yml
#
# Returns: prints total error count. Exit code 0 always (errors are data, not failures).
# =============================================================================

set -uo pipefail

TERRAFORM_DIR="${1:?Usage: validate_syntax.sh <tf_dir> <docker_jira_dir> <docker_github_dir> [ci_yaml]}"
DOCKER_JIRA_DIR="${2:?}"
DOCKER_GITHUB_DIR="${3:?}"
CI_YAML="${4:-}"

TOTAL_ERRORS=0
TF_ERRORS=0
DOCKER_ERRORS=0
YAML_ERRORS=0

YELLOW='\033[1;33m'
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  Syntax Validation${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"

# ── Terraform validation ──
echo -e "\n${YELLOW}[1/3] Terraform validation${NC}"
if [ -d "$TERRAFORM_DIR" ] && ls "$TERRAFORM_DIR"/*.tf 1>/dev/null 2>&1; then
    # Create a temp directory with just the tf files for validation
    TEMP_TF=$(mktemp -d)
    cp "$TERRAFORM_DIR"/*.tf "$TEMP_TF/" 2>/dev/null

    # Run terraform init (required before validate)
    if command -v terraform &>/dev/null; then
        cd "$TEMP_TF"
        INIT_OUTPUT=$(terraform init -backend=false 2>&1)
        INIT_EXIT=$?

        if [ $INIT_EXIT -ne 0 ]; then
            echo "  terraform init failed:"
            echo "$INIT_OUTPUT" | grep -i "error" | head -5
            TF_ERRORS=$((TF_ERRORS + 1))
        fi

        # Run terraform validate
        VALIDATE_OUTPUT=$(terraform validate 2>&1)
        VALIDATE_EXIT=$?

        if [ $VALIDATE_EXIT -ne 0 ]; then
            # Count error lines
            ERROR_COUNT=$(echo "$VALIDATE_OUTPUT" | grep -c -i "error")
            TF_ERRORS=$((TF_ERRORS + ERROR_COUNT))
            echo "  terraform validate found $ERROR_COUNT error(s):"
            echo "$VALIDATE_OUTPUT" | grep -i "error" | head -10 | sed 's/^/    /'
        else
            echo -e "  ${GREEN}terraform validate: PASSED${NC}"
        fi

        cd - >/dev/null
        rm -rf "$TEMP_TF"
    else
        # Fallback: basic HCL syntax check via grep
        echo "  terraform CLI not found — running basic syntax checks"
        for tf_file in "$TERRAFORM_DIR"/*.tf; do
            # Check for common syntax issues
            if grep -q 'resource\s*"' "$tf_file" || grep -q 'variable\s*"' "$tf_file" || grep -q 'output\s*"' "$tf_file" || grep -q 'provider\s*"' "$tf_file"; then
                echo -e "  ${GREEN}$(basename "$tf_file"): basic structure OK${NC}"
            else
                echo -e "  ${RED}$(basename "$tf_file"): no recognisable HCL blocks found${NC}"
                TF_ERRORS=$((TF_ERRORS + 1))
            fi
        done

        # Check for required_providers block
        if ! grep -q "required_providers" "$TERRAFORM_DIR"/*.tf 2>/dev/null; then
            echo -e "  ${RED}Missing: required_providers block${NC}"
            TF_ERRORS=$((TF_ERRORS + 1))
        fi
    fi
else
    echo -e "  ${RED}No .tf files found in $TERRAFORM_DIR${NC}"
    TF_ERRORS=$((TF_ERRORS + 1))
fi
echo "  Terraform errors: $TF_ERRORS"

# ── Dockerfile validation ──
echo -e "\n${YELLOW}[2/3] Dockerfile validation${NC}"

validate_dockerfile() {
    local dir="$1"
    local name="$2"
    local errors=0

    if [ ! -f "$dir/Dockerfile" ]; then
        echo -e "  ${RED}$name: Dockerfile not found${NC}"
        return 1
    fi

    if command -v hadolint &>/dev/null; then
        HADOLINT_OUTPUT=$(hadolint "$dir/Dockerfile" 2>&1)
        HADOLINT_EXIT=$?
        if [ $HADOLINT_EXIT -ne 0 ]; then
            errors=$(echo "$HADOLINT_OUTPUT" | grep -c -E "^$dir/Dockerfile:")
            echo "  $name hadolint found $errors issue(s):"
            echo "$HADOLINT_OUTPUT" | head -5 | sed 's/^/    /'
        else
            echo -e "  ${GREEN}$name hadolint: PASSED${NC}"
        fi
    else
        echo "  hadolint not found — running basic Dockerfile checks for $name"

        # Check for FROM
        if ! grep -q "^FROM " "$dir/Dockerfile"; then
            echo -e "  ${RED}$name: missing FROM instruction${NC}"
            errors=$((errors + 1))
        fi

        # Check for EXPOSE
        if ! grep -q "^EXPOSE " "$dir/Dockerfile"; then
            echo -e "  ${RED}$name: missing EXPOSE instruction${NC}"
            errors=$((errors + 1))
        fi

        # Check for CMD or ENTRYPOINT
        if ! grep -q -E "^(CMD|ENTRYPOINT) " "$dir/Dockerfile"; then
            echo -e "  ${RED}$name: missing CMD/ENTRYPOINT${NC}"
            errors=$((errors + 1))
        fi

        # Check for HEALTHCHECK
        if ! grep -q "^HEALTHCHECK " "$dir/Dockerfile"; then
            echo -e "  ${RED}$name: missing HEALTHCHECK${NC}"
            errors=$((errors + 1))
        fi

        if [ $errors -eq 0 ]; then
            echo -e "  ${GREEN}$name basic checks: PASSED${NC}"
        fi
    fi

    return $errors
}

JIRA_DOCKER_ERRORS=0
GITHUB_DOCKER_ERRORS=0

validate_dockerfile "$DOCKER_JIRA_DIR" "MCP-Jira" || JIRA_DOCKER_ERRORS=$?
validate_dockerfile "$DOCKER_GITHUB_DIR" "MCP-GitHub" || GITHUB_DOCKER_ERRORS=$?
DOCKER_ERRORS=$((JIRA_DOCKER_ERRORS + GITHUB_DOCKER_ERRORS))
echo "  Dockerfile errors: $DOCKER_ERRORS"

# ── YAML validation ──
echo -e "\n${YELLOW}[3/3] YAML validation${NC}"
if [ -n "$CI_YAML" ] && [ -f "$CI_YAML" ]; then
    if command -v yamllint &>/dev/null; then
        YAML_OUTPUT=$(yamllint -d "{extends: default, rules: {line-length: {max: 300}, truthy: disable, document-start: disable}}" "$CI_YAML" 2>&1)
        YAML_EXIT=$?
        if [ $YAML_EXIT -ne 0 ]; then
            YAML_ERRORS=$(echo "$YAML_OUTPUT" | grep -c "error")
            echo "  yamllint found $YAML_ERRORS error(s):"
            echo "$YAML_OUTPUT" | grep "error" | head -5 | sed 's/^/    /'
        else
            echo -e "  ${GREEN}yamllint: PASSED${NC}"
        fi
    else
        echo "  yamllint not found — running basic YAML checks"
        # Basic check: valid YAML via Python
        if python3 -c "import yaml; yaml.safe_load(open('$CI_YAML'))" 2>/dev/null; then
            echo -e "  ${GREEN}YAML parse: PASSED${NC}"
        else
            echo -e "  ${RED}YAML parse: FAILED${NC}"
            YAML_ERRORS=$((YAML_ERRORS + 1))
        fi
    fi
else
    echo "  No CI/CD YAML path provided or file not found — skipping"
fi
echo "  YAML errors: $YAML_ERRORS"

# ── Summary ──
TOTAL_ERRORS=$((TF_ERRORS + DOCKER_ERRORS + YAML_ERRORS))

echo -e "\n${YELLOW}═══════════════════════════════════════════════════${NC}"
echo "  SYNTAX VALIDATION SUMMARY"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo "  Terraform errors:  $TF_ERRORS"
echo "  Dockerfile errors: $DOCKER_ERRORS"
echo "  YAML errors:       $YAML_ERRORS"
echo "  ─────────────────────────"
echo "  TOTAL ERRORS:      $TOTAL_ERRORS"
echo ""
echo ">> For results.csv: syntax_errors_count = $TOTAL_ERRORS"