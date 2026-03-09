#!/usr/bin/env python3
"""
test_endpoints.py — Functional endpoint verification

Sends test payloads to all MCP server endpoints and validates response
structure and content against expected_config.json.

Usage:
    python test_endpoints.py --host 52.59.191.104
    python test_endpoints.py --host 52.59.191.104 --config docs/expected_config.json

"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

def fetch(url: str, timeout: int = 10) -> tuple[int, dict | None, float]:
    """Make an HTTP GET request. Returns (status_code, parsed_json, duration_ms)."""
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            duration = (time.perf_counter() - start) * 1000
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = None
            return resp.status, data, duration
    except urllib.error.HTTPError as e:
        duration = (time.perf_counter() - start) * 1000
        return e.code, None, duration
    except Exception as e:
        duration = (time.perf_counter() - start) * 1000
        return 0, None, duration

def test_server(host: str, port: int, server_config: dict) -> dict:
    """Test all endpoints for a single MCP server."""
    base = f"http://{host}:{port}"
    service_name = server_config["service_name"]
    results = {"service": service_name, "port": port, "tests": [], "passed": 0, "failed": 0}

    print(f"\n  Testing {service_name} on {base}")
    print(f"  {'─' * 50}")

    # Test health endpoint
    url = f"{base}{server_config['health_endpoint']}"
    status, data, ms = fetch(url)
    expected = server_config["health_response"]
    ok = (status == 200 and data is not None and
          data.get("status") == expected["status"] and
          data.get("service") == expected["service"])
    results["tests"].append({"endpoint": "/health", "pass": ok, "status": status, "ms": round(ms, 1)})
    icon = "✓" if ok else "✗"
    print(f"  {icon} /health — HTTP {status}, {ms:.0f}ms {'PASS' if ok else 'FAIL'}")
    if ok:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # Test manifest endpoint
    url = f"{base}{server_config['manifest_endpoint']}"
    status, data, ms = fetch(url)
    ok = status == 200 and data is not None and "endpoints" in data
    results["tests"].append({"endpoint": "/manifest", "pass": ok, "status": status, "ms": round(ms, 1)})
    icon = "✓" if ok else "✗"
    print(f"  {icon} /manifest — HTTP {status}, {ms:.0f}ms {'PASS' if ok else 'FAIL'}")
    if ok:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # Test functional endpoints
    for ep_config in server_config["functional_endpoints"]:
        path = ep_config["path"]
        params = ep_config["required_params"]
        expected_field = ep_config["expected_response_field"]
        expected_value = ep_config["expected_response_value"]

        # Build test query params
        test_params = {}
        for p in params:
            if p in ("project", "owner"):
                test_params[p] = "TEST"
            elif p in ("summary", "title"):
                test_params[p] = "Automated-test"
            elif p in ("repo",):
                test_params[p] = "test-repo"
            elif p in ("ticket_key",):
                test_params[p] = "TEST-123"
            elif p in ("issue_number",):
                test_params[p] = "1"
            elif p in ("priority",):
                test_params[p] = "Medium"
            else:
                test_params[p] = "test"

        query = urllib.parse.urlencode(test_params)
        url = f"{base}{path}?{query}"
        status, data, ms = fetch(url)

        ok = (status == 200 and data is not None and
              data.get(expected_field) == expected_value)
        results["tests"].append({
            "endpoint": path, "pass": ok, "status": status,
            "ms": round(ms, 1), "params": test_params
        })
        icon = "✓" if ok else "✗"
        detail = f"response.{expected_field}={data.get(expected_field) if data else 'N/A'}" if data else "no response"
        print(f"  {icon} {path} — HTTP {status}, {ms:.0f}ms {'PASS' if ok else 'FAIL'} ({detail})")
        if ok:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results

def main():
    parser = argparse.ArgumentParser(description="Test MCP server functional endpoints")
    parser.add_argument("--host", required=True, help="EC2 public IP")
    parser.add_argument("--jira-port", type=int, default=80)
    parser.add_argument("--github-port", type=int, default=81)
    parser.add_argument("--config", default="docs/expected_config.json",
                        help="Path to expected_config.json")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Load config
    try:
        with open(args.config) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {args.config}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  FUNCTIONAL ENDPOINT TESTS")
    print(f"  Host: {args.host}")
    print(f"{'='*60}")

    all_results = {}
    total_passed = 0
    total_failed = 0

    # Test Jira
    jira_results = test_server(args.host, args.jira_port, config["mcp_servers"]["jira"])
    all_results["jira"] = jira_results
    total_passed += jira_results["passed"]
    total_failed += jira_results["failed"]

    # Test GitHub
    github_results = test_server(args.host, args.github_port, config["mcp_servers"]["github"])
    all_results["github"] = github_results
    total_passed += github_results["passed"]
    total_failed += github_results["failed"]

    # Summary
    total = total_passed + total_failed
    print(f"\n{'='*60}")
    print(f"  FUNCTIONAL TEST SUMMARY")
    print(f"{'='*60}")
    print(f"  MCP-Jira:   {jira_results['passed']}/{jira_results['passed']+jira_results['failed']} passed")
    print(f"  MCP-GitHub: {github_results['passed']}/{github_results['passed']+github_results['failed']} passed")
    print(f"  Total:      {total_passed}/{total} passed")
    print()
    print(f">> For results.csv:")
    print(f"   functional_endpoint_pass = {1 if total_failed == 0 else 0}")

    if args.json:
        print(json.dumps(all_results, indent=2))

    sys.exit(0 if total_failed == 0 else 1)

if __name__ == "__main__":
    main()