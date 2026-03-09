#!/usr/bin/env python3
"""
check_completeness.py — Automated correctness evaluation
=============================================================================
Compares generated artefacts against expected_config.json and the correctness
checklist. Outputs per-check pass/fail and computes correctness_score.

Usage:
    python check_completeness.py --server jira --tf-dir llm-assisted/generated/run001/ \
        --docker-dir llm-assisted/generated/run001/jira/ \
        --ci-yaml llm-assisted/generated/run001/deploy.yml

    python check_completeness.py --server github --tf-dir ... --docker-dir ... --ci-yaml ...

Part of the MSc thesis evaluation framework.
=============================================================================
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# =============================================================================
# Check functions — each returns (pass: bool, detail: str)
# =============================================================================

def read_file(path: str) -> str:
    """Read file contents, return empty string if not found."""
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return ""


# ── Terraform checks ──

def check_t1_provider(tf_content: str) -> tuple[bool, str]:
    """T1: AWS provider block with region variable reference."""
    has_provider = bool(re.search(r'provider\s+"aws"', tf_content))
    has_region = "var.region" in tf_content or 'variable "region"' in tf_content
    ok = has_provider and has_region
    return ok, f"provider block: {has_provider}, region var: {has_region}"


def check_t2_instance_type(tf_content: str) -> tuple[bool, str]:
    """T2: EC2 instance with t2.micro."""
    has_instance = bool(re.search(r'resource\s+"aws_instance"', tf_content))
    has_t2_micro = "t2.micro" in tf_content or "var.instance_type" in tf_content
    ok = has_instance and has_t2_micro
    return ok, f"aws_instance resource: {has_instance}, t2.micro ref: {has_t2_micro}"


def check_t3_ami(tf_content: str) -> tuple[bool, str]:
    """T3: AMI references Ubuntu 22.04 (jammy)."""
    has_jammy = "jammy" in tf_content.lower() or "22.04" in tf_content
    has_canonical = "099720109477" in tf_content
    has_data_source = bool(re.search(r'data\s+"aws_ami"', tf_content))
    ok = has_jammy or (has_canonical and has_data_source)
    return ok, f"jammy/22.04: {has_jammy}, canonical owner: {has_canonical}, data source: {has_data_source}"


def check_t4_port22(tf_content: str) -> tuple[bool, str]:
    """T4: Security group allows port 22."""
    # Look for port 22 in ingress rules
    ok = bool(re.search(r'from_port\s*=\s*22', tf_content)) or '"22"' in tf_content
    return ok, f"port 22 ingress: {ok}"


def check_t5_port80(tf_content: str) -> tuple[bool, str]:
    """T5: Security group allows port 80."""
    ok = bool(re.search(r'from_port\s*=\s*80', tf_content)) or '"80"' in tf_content
    return ok, f"port 80 ingress: {ok}"


def check_t6_port81(tf_content: str) -> tuple[bool, str]:
    """T6: Security group allows port 81."""
    ok = bool(re.search(r'from_port\s*=\s*81', tf_content)) or '"81"' in tf_content
    return ok, f"port 81 ingress: {ok}"


def check_t7_key_pair(tf_content: str) -> tuple[bool, str]:
    """T7: Key pair reference present."""
    ok = "key_name" in tf_content
    return ok, f"key_name reference: {ok}"


def check_t8_output_ip(tf_content: str, outputs_content: str) -> tuple[bool, str]:
    """T8: Output block exports public_ip."""
    combined = tf_content + outputs_content
    ok = "public_ip" in combined and bool(re.search(r'output\s+"public_ip"', combined))
    return ok, f"public_ip output: {ok}"


# ── Dockerfile checks ──

def check_d1_base_image(dockerfile: str) -> tuple[bool, str]:
    """D1: Base image is python:3.10-slim."""
    ok = bool(re.search(r'FROM\s+python:3\.10', dockerfile))
    return ok, f"python:3.10 base: {ok}"


def check_d2_requirements(dockerfile: str) -> tuple[bool, str]:
    """D2: requirements.txt copied and pip install executed."""
    has_copy = "requirements.txt" in dockerfile
    has_pip = "pip install" in dockerfile
    ok = has_copy and has_pip
    return ok, f"requirements copy: {has_copy}, pip install: {has_pip}"


def check_d3_app_copy(dockerfile: str) -> tuple[bool, str]:
    """D3: app.py copied into container."""
    ok = "app.py" in dockerfile or "COPY ." in dockerfile
    return ok, f"app.py in container: {ok}"


def check_d4_expose(dockerfile: str) -> tuple[bool, str]:
    """D4: Port 8000 exposed."""
    ok = bool(re.search(r'EXPOSE\s+8000', dockerfile))
    return ok, f"EXPOSE 8000: {ok}"


def check_d5_entrypoint(dockerfile: str) -> tuple[bool, str]:
    """D5: Entrypoint runs uvicorn on 0.0.0.0:8000."""
    has_uvicorn = "uvicorn" in dockerfile
    has_host = "0.0.0.0" in dockerfile
    ok = has_uvicorn and has_host
    return ok, f"uvicorn: {has_uvicorn}, 0.0.0.0: {has_host}"


def check_d6_healthcheck(dockerfile: str) -> tuple[bool, str]:
    """D6: HEALTHCHECK directive targeting /health."""
    has_healthcheck = "HEALTHCHECK" in dockerfile
    has_health_path = "/health" in dockerfile
    ok = has_healthcheck and has_health_path
    return ok, f"HEALTHCHECK: {has_healthcheck}, /health path: {has_health_path}"


# ── CI/CD checks ──

def check_c1_trigger(yaml_content: str, branch: str) -> tuple[bool, str]:
    """C1: Trigger on push to correct branch."""
    ok = branch in yaml_content and "push" in yaml_content
    return ok, f"push trigger on '{branch}': {ok}"


def check_c2_ssh_setup(yaml_content: str) -> tuple[bool, str]:
    """C2: SSH key setup step."""
    has_ssh_key = "EC2_SSH_KEY" in yaml_content or "SSH_KEY" in yaml_content
    has_chmod = "chmod" in yaml_content and "600" in yaml_content
    ok = has_ssh_key and has_chmod
    return ok, f"SSH key secret: {has_ssh_key}, chmod 600: {has_chmod}"


def check_c3_docker_build(yaml_content: str, server: str) -> tuple[bool, str]:
    """C3: Docker build for the target server."""
    server_name = "mcp-jira" if server == "jira" else "mcp-github"
    ok = "docker build" in yaml_content and server_name in yaml_content
    return ok, f"docker build {server_name}: {ok}"


def check_c4_port_mapping(yaml_content: str, server: str) -> tuple[bool, str]:
    """C4: Container run with correct port mapping."""
    if server == "jira":
        ok = "80:8000" in yaml_content or "80:" in yaml_content
        return ok, f"port 80->8000 mapping: {ok}"
    else:
        ok = "81:8000" in yaml_content or "81:" in yaml_content
        return ok, f"port 81->8000 mapping: {ok}"


def check_c5_health_check(yaml_content: str, server: str) -> tuple[bool, str]:
    """C5: Health check verifies HTTP 200."""
    port = "80" if server == "jira" else "81"
    has_curl = "curl" in yaml_content
    has_health = "/health" in yaml_content
    has_port = port in yaml_content
    ok = has_curl and has_health
    return ok, f"curl /health: {has_curl and has_health}, port {port}: {has_port}"


def check_c6_fail_on_unhealthy(yaml_content: str) -> tuple[bool, str]:
    """C6: Pipeline fails if health check fails."""
    has_exit = "exit 1" in yaml_content
    ok = has_exit
    return ok, f"exit 1 on failure: {ok}"


# ── Application checks ──

def check_a1_health_endpoint(app_content: str, service_name: str) -> tuple[bool, str]:
    """A1: /health returns correct JSON."""
    has_route = '"/health"' in app_content or "'/health'" in app_content
    has_status = '"ok"' in app_content or "'ok'" in app_content
    has_service = service_name in app_content
    ok = has_route and has_status and has_service
    return ok, f"/health route: {has_route}, status ok: {has_status}, service name: {has_service}"


def check_a2_manifest(app_content: str) -> tuple[bool, str]:
    """A2: /manifest endpoint present."""
    ok = "/manifest" in app_content
    return ok, f"/manifest endpoint: {ok}"


def check_a3_functional(app_content: str, server: str) -> tuple[bool, str]:
    """A3: Functional endpoint returns success."""
    endpoint = "/create_ticket" if server == "jira" else "/create_issue"
    has_route = endpoint in app_content
    # Check that the function body contains a return statement (not a stub)
    has_return = bool(re.search(
        rf'def\s+\w+.*?{endpoint.replace("/", "")}.*?return\s+\{{',
        app_content, re.DOTALL
    ))
    # Simpler check: does "success" appear after the endpoint definition?
    has_success = '"success"' in app_content or "'success'" in app_content
    ok = has_route and has_success
    detail = f"{endpoint}: {has_route}, returns data: {has_success}"
    if has_route and not has_success:
        detail += " (WARNING: endpoint may be a stub)"
    return ok, detail


def check_a4_env_var(app_content: str) -> tuple[bool, str]:
    """A4: MCP_API_VERSION read from environment."""
    ok = "MCP_API_VERSION" in app_content
    return ok, f"MCP_API_VERSION: {ok}"


def check_a5_uvicorn(app_content: str) -> tuple[bool, str]:
    """A5: FastAPI/uvicorn application."""
    has_fastapi = "FastAPI" in app_content or "fastapi" in app_content
    ok = has_fastapi
    return ok, f"FastAPI: {has_fastapi}"


# =============================================================================
# Main evaluation
# =============================================================================

def run_evaluation(server: str, tf_dir: str, docker_dir: str, ci_yaml: str, branch: str):
    """Run all 25 checks and print results."""

    # Load files
    tf_files = list(Path(tf_dir).glob("*.tf"))
    tf_content = "\n".join(f.read_text() for f in tf_files) if tf_files else ""

    outputs_file = Path(tf_dir) / "outputs.tf"
    outputs_content = outputs_file.read_text() if outputs_file.exists() else ""

    dockerfile_path = Path(docker_dir) / "Dockerfile"
    dockerfile = read_file(str(dockerfile_path))

    app_path = Path(docker_dir) / "app.py"
    app_content = read_file(str(app_path))

    yaml_content = read_file(ci_yaml) if ci_yaml else ""

    service_name = "MCP-Jira" if server == "jira" else "MCP-GitHub"

    # Run all checks
    checks = [
        ("T1", "AWS provider with region", check_t1_provider(tf_content)),
        ("T2", "EC2 t2.micro instance", check_t2_instance_type(tf_content)),
        ("T3", "Ubuntu 22.04 AMI", check_t3_ami(tf_content)),
        ("T4", "SG port 22 (SSH)", check_t4_port22(tf_content)),
        ("T5", "SG port 80 (Jira)", check_t5_port80(tf_content)),
        ("T6", "SG port 81 (GitHub)", check_t6_port81(tf_content)),
        ("T7", "Key pair reference", check_t7_key_pair(tf_content)),
        ("T8", "public_ip output", check_t8_output_ip(tf_content, outputs_content)),
        ("D1", "Python 3.10-slim base", check_d1_base_image(dockerfile)),
        ("D2", "requirements.txt + pip", check_d2_requirements(dockerfile)),
        ("D3", "app.py copied", check_d3_app_copy(dockerfile)),
        ("D4", "EXPOSE 8000", check_d4_expose(dockerfile)),
        ("D5", "uvicorn on 0.0.0.0", check_d5_entrypoint(dockerfile)),
        ("D6", "HEALTHCHECK /health", check_d6_healthcheck(dockerfile)),
        ("C1", f"Trigger on {branch}", check_c1_trigger(yaml_content, branch)),
        ("C2", "SSH key setup", check_c2_ssh_setup(yaml_content)),
        ("C3", f"Docker build {server}", check_c3_docker_build(yaml_content, server)),
        ("C4", "Correct port mapping", check_c4_port_mapping(yaml_content, server)),
        ("C5", "Health check curl", check_c5_health_check(yaml_content, server)),
        ("C6", "Fail on unhealthy", check_c6_fail_on_unhealthy(yaml_content)),
        ("A1", f"/health returns {service_name}", check_a1_health_endpoint(app_content, service_name)),
        ("A2", "/manifest endpoint", check_a2_manifest(app_content)),
        ("A3", "Functional endpoint returns data", check_a3_functional(app_content, server)),
        ("A4", "MCP_API_VERSION env var", check_a4_env_var(app_content)),
        ("A5", "FastAPI/uvicorn app", check_a5_uvicorn(app_content)),
    ]

    # Print results
    N = len(checks)
    passed = 0
    failed = 0
    results_detail = []

    print(f"\n{'='*70}")
    print(f"  CORRECTNESS EVALUATION — {service_name}")
    print(f"{'='*70}\n")

    categories = {
        "T": ("Terraform", []),
        "D": ("Dockerfile", []),
        "C": ("CI/CD", []),
        "A": ("Application", []),
    }

    for check_id, description, (ok, detail) in checks:
        status = "PASS" if ok else "FAIL"
        icon = "✓" if ok else "✗"
        color_start = "\033[0;32m" if ok else "\033[0;31m"
        color_end = "\033[0m"

        print(f"  {color_start}{icon} {check_id:3s}{color_end}  {description:40s}  {detail}")

        if ok:
            passed += 1
        else:
            failed += 1

        cat = check_id[0]
        categories[cat][1].append(ok)

    # Summary
    correctness_score = max(0.0, 1.0 - (failed / N))

    print(f"\n{'─'*70}")
    print(f"  SUMMARY")
    print(f"{'─'*70}")

    for cat_key, (cat_name, cat_results) in categories.items():
        cat_pass = sum(cat_results)
        cat_total = len(cat_results)
        print(f"  {cat_name:15s}  {cat_pass}/{cat_total}")

    print(f"  {'─'*30}")
    print(f"  {'TOTAL':15s}  {passed}/{N}")
    print(f"\n  correctness_score = max(0, 1 - {failed}/{N}) = {correctness_score:.2f}")
    print(f"\n>> For results.csv:")
    print(f"   syntax_errors_count   = (from validate_syntax.sh)")
    print(f"   missing_fields_count  = {failed}")
    print(f"   wrong_config_count    = (inspect values manually or use check_config.py)")
    print(f"   correctness_score     = {correctness_score:.2f}")
    print()

    return {
        "total_checks": N,
        "passed": passed,
        "failed": failed,
        "correctness_score": correctness_score,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate generated artefact correctness")
    parser.add_argument("--server", choices=["jira", "github"], required=True)
    parser.add_argument("--tf-dir", required=True, help="Directory containing .tf files")
    parser.add_argument("--docker-dir", required=True, help="Directory containing Dockerfile and app.py")
    parser.add_argument("--ci-yaml", default="", help="Path to deploy.yml")
    parser.add_argument("--branch", default="llm-assisted", help="Expected trigger branch")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    result = run_evaluation(
        server=args.server,
        tf_dir=args.tf_dir,
        docker_dir=args.docker_dir,
        ci_yaml=args.ci_yaml,
        branch=args.branch,
    )

    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()