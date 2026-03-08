#!/usr/bin/env python3
"""
run_experiment.py — Full experiment orchestration
=============================================================================
Runs a single complete experiment cycle for one (server, approach, phase)
combination. Chains together: generation (LLM only) → deployment → health
check → functional test → completeness check → writes a row to results.csv.

Usage:
    # Run a manual baseline experiment for Jira, Phase A
    python run_experiment.py --server jira --approach manual --phase A_initial

    # Run an LLM-assisted experiment for GitHub, Phase A
    python run_experiment.py --server github --approach llm --phase A_initial

    # Run all Phase A experiments (both servers, both approaches)
    python run_experiment.py --all-phase-a

    # Dry run (print what would happen without executing)
    python run_experiment.py --server jira --approach llm --phase A_initial --dry-run

Required environment variables:
    EC2_IP        — Public IP of the EC2 instance
    PEM_PATH      — Path to the SSH private key file
    OPENAI_API_KEY — (LLM runs only) OpenAI API key

Part of the MSc thesis evaluation framework.
=============================================================================
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# =============================================================================
# Configuration
# =============================================================================

RESULTS_CSV = Path("evaluation/results.csv")
LOGS_DIR = Path("logs")
MANUAL_BASELINE_DIR = Path("manual-baseline")
LLM_ASSISTED_DIR = Path("llm-assisted")

JIRA_PORT = 80
GITHUB_PORT = 81

CSV_HEADERS = [
    "run_id", "timestamp_start", "timestamp_end", "server", "approach", "phase",
    "syntax_errors_count", "missing_fields_count", "wrong_config_count",
    "manual_edits_lines", "correctness_score", "health_endpoint_pass",
    "functional_endpoint_pass", "t_gen_secs", "t_author_secs", "t_pipeline_secs",
    "t_total_secs", "speedup", "peak_memory_mb", "disk_usage_mb", "success",
    "attempts", "rollback_triggered", "failure_category", "prompts_to_fix",
    "edit_span_lines", "time_to_adapt_secs", "adaptation_success",
    "aws_runtime_mins", "aws_cost_eur", "tokens_prompt", "tokens_completion",
    "tokens_total", "llm_cost_eur", "total_cost_eur", "notes",
]


def get_run_count(server: str, approach: str, phase: str) -> int:
    """Count existing runs for this combination to determine the next run number."""
    if not RESULTS_CSV.exists():
        return 0
    count = 0
    with open(RESULTS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("server") == server and
                    row.get("approach") == approach and
                    row.get("phase") == phase):
                count += 1
    return count


def ensure_csv_exists():
    """Create results.csv with headers if it doesn't exist or is empty."""
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not RESULTS_CSV.exists() or RESULTS_CSV.stat().st_size == 0:
        with open(RESULTS_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
        print(f"  Created {RESULTS_CSV} with headers")


def append_row(row: dict):
    """Append a single row to results.csv."""
    ensure_csv_exists()
    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(row)
    print(f"  ✓ Row written to {RESULTS_CSV}")


def run_cmd(cmd: str, description: str, capture: bool = True) -> tuple[int, str]:
    """Run a shell command and return (exit_code, output)."""
    print(f"  → {description}")
    result = subprocess.run(
        cmd, shell=True, capture_output=capture, text=True, timeout=300
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 and capture:
        print(f"    WARNING: exit code {result.returncode}")
        if output.strip():
            for line in output.strip().split("\n")[:5]:
                print(f"    {line}")
    return result.returncode, output


# =============================================================================
# Step functions
# =============================================================================

def step_generate_llm(server: str, run_id: str) -> dict:
    """Generate artefacts using the LLM pipeline. Returns generation metadata."""
    print(f"\n{'─'*60}")
    print(f"  STEP 1: LLM Artefact Generation")
    print(f"{'─'*60}")

    start = time.perf_counter()

    # Generate terraform
    exit_tf, out_tf = run_cmd(
        f"python {LLM_ASSISTED_DIR}/run_llm.py --artefact terraform --server {server} --no-retry",
        "Generating Terraform..."
    )

    # Generate docker
    exit_dk, out_dk = run_cmd(
        f"python {LLM_ASSISTED_DIR}/run_llm.py --artefact docker --server {server} --no-retry",
        f"Generating Docker ({server})..."
    )

    # Generate CI/CD
    exit_ci, out_ci = run_cmd(
        f"python {LLM_ASSISTED_DIR}/run_llm.py --artefact ci --server both --no-retry",
        "Generating CI/CD..."
    )

    duration = time.perf_counter() - start

    # Parse token usage from output
    combined_output = out_tf + out_dk + out_ci
    tokens_prompt = 0
    tokens_completion = 0
    tokens_total = 0

    for line in combined_output.split("\n"):
        if "tokens_prompt" in line and "=" in line:
            try:
                tokens_prompt += int(line.split("=")[1].strip())
            except (ValueError, IndexError):
                pass
        if "tokens_completion" in line and "=" in line:
            try:
                tokens_completion += int(line.split("=")[1].strip())
            except (ValueError, IndexError):
                pass
        if "tokens_total" in line and "=" in line and "tokens_prompt" not in line and "tokens_completion" not in line:
            try:
                tokens_total += int(line.split("=")[1].strip())
            except (ValueError, IndexError):
                pass

    if tokens_total == 0:
        tokens_total = tokens_prompt + tokens_completion

    # Find the generated directory (most recent)
    gen_dir = LLM_ASSISTED_DIR / "generated"
    if gen_dir.exists():
        subdirs = sorted(gen_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        latest_dirs = [d for d in subdirs[:5] if d.is_dir()]
    else:
        latest_dirs = []

    return {
        "t_gen_secs": round(duration, 1),
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "tokens_total": tokens_total,
        "generation_success": exit_tf == 0 and exit_dk == 0 and exit_ci == 0,
        "generated_dirs": [str(d) for d in latest_dirs],
    }


def step_deploy(ec2_ip: str, pem_path: str, approach: str, server: str) -> dict:
    """Deploy containers to EC2. Returns deployment metadata."""
    print(f"\n{'─'*60}")
    print(f"  STEP 2: Deploy to EC2")
    print(f"{'─'*60}")

    start = time.perf_counter()
    docker_base = MANUAL_BASELINE_DIR / "docker" if approach == "manual" else LLM_ASSISTED_DIR / "docker"

    ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"

    # Copy files
    for svc in ["jira", "github"]:
        src = docker_base / svc
        if not src.exists():
            # For LLM: files might be in generated/ — try to find them
            gen_dir = LLM_ASSISTED_DIR / "generated"
            if gen_dir.exists():
                for d in sorted(gen_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    candidate = d / svc
                    if candidate.exists() and (candidate / "Dockerfile").exists():
                        src = candidate
                        break
            if not src.exists():
                print(f"    WARNING: {src} not found, skipping {svc}")
                continue

        exit_code, _ = run_cmd(
            f"scp {ssh_opts} -i {pem_path} -r {src} ubuntu@{ec2_ip}:/home/ubuntu/{svc}",
            f"Copying {svc} to EC2..."
        )

    # Build and run containers
    for svc, port in [("jira", JIRA_PORT), ("github", GITHUB_PORT)]:
        run_cmd(
            f'ssh {ssh_opts} -i {pem_path} ubuntu@{ec2_ip} '
            f'"cd /home/ubuntu/{svc} && docker build -t mcp-{svc} . && '
            f'docker stop mcp-{svc} 2>/dev/null; docker rm mcp-{svc} 2>/dev/null; '
            f'docker run -d --name mcp-{svc} -p {port}:8000 --restart unless-stopped mcp-{svc}"',
            f"Building and starting mcp-{svc} on port {port}..."
        )

    duration = time.perf_counter() - start
    return {"t_pipeline_secs": round(duration, 1)}


def step_health_check(ec2_ip: str) -> dict:
    """Run health checks. Returns health check results."""
    print(f"\n{'─'*60}")
    print(f"  STEP 3: Health Checks")
    print(f"{'─'*60}")

    import urllib.request
    import urllib.error

    results = {}
    for name, port in [("jira", JIRA_PORT), ("github", GITHUB_PORT)]:
        url = f"http://{ec2_ip}:{port}/health"
        passed = False
        for attempt in range(1, 13):
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        body = json.loads(resp.read().decode())
                        if body.get("status") == "ok":
                            print(f"  ✓ {name} healthy (attempt {attempt}): {body}")
                            passed = True
                            break
            except Exception:
                pass
            print(f"    {name} attempt {attempt}/12 — waiting 5s...")
            time.sleep(5)

        if not passed:
            print(f"  ✗ {name} FAILED health check")
        results[name] = passed

    both_pass = all(results.values())
    return {"health_endpoint_pass": 1 if both_pass else 0, "per_server": results}


def step_functional_test(ec2_ip: str) -> dict:
    """Run functional endpoint tests."""
    print(f"\n{'─'*60}")
    print(f"  STEP 4: Functional Tests")
    print(f"{'─'*60}")

    import urllib.request
    import urllib.error
    import urllib.parse

    tests = {
        "jira": [
            ("/create_ticket", {"project": "TEST", "summary": "Run-test", "priority": "Medium"}),
            ("/get_ticket", {"ticket_key": "TEST-123"}),
        ],
        "github": [
            ("/create_issue", {"owner": "test", "repo": "test-repo", "title": "Run-test"}),
            ("/get_issue", {"owner": "test", "repo": "test-repo", "issue_number": "1"}),
        ],
    }

    all_pass = True
    for server, endpoints in tests.items():
        port = JIRA_PORT if server == "jira" else GITHUB_PORT
        for path, params in endpoints:
            query = urllib.parse.urlencode(params)
            url = f"http://{ec2_ip}:{port}{path}?{query}"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = json.loads(resp.read().decode())
                    ok = body.get("status") == "success"
                    icon = "✓" if ok else "✗"
                    print(f"  {icon} {server}{path} — {'PASS' if ok else 'FAIL'}")
                    if not ok:
                        all_pass = False
            except Exception as e:
                print(f"  ✗ {server}{path} — ERROR: {e}")
                all_pass = False

    return {"functional_endpoint_pass": 1 if all_pass else 0}


def step_completeness_check(server: str, approach: str) -> dict:
    """Run check_completeness.py and parse results."""
    print(f"\n{'─'*60}")
    print(f"  STEP 5: Completeness Check")
    print(f"{'─'*60}")

    if approach == "manual":
        tf_dir = str(MANUAL_BASELINE_DIR / "terraform")
        docker_dir = str(MANUAL_BASELINE_DIR / "docker" / server)
        ci_yaml = ".github/workflows/deploy.yml"
        branch = "manual-baseline"
    else:
        # Find most recent generated dirs
        gen_dir = LLM_ASSISTED_DIR / "generated"
        tf_dir = ""
        docker_dir = ""
        ci_yaml = ""
        branch = "llm-assisted"

        if gen_dir.exists():
            for d in sorted(gen_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if not d.is_dir():
                    continue
                if not tf_dir and (d / "main.tf").exists():
                    tf_dir = str(d)
                if not docker_dir and (d / server / "Dockerfile").exists():
                    docker_dir = str(d / server)
                if not ci_yaml and (d / "deploy.yml").exists():
                    ci_yaml = str(d / "deploy.yml")
                if tf_dir and docker_dir and ci_yaml:
                    break

    if not tf_dir or not docker_dir:
        print("  WARNING: Could not find generated files for completeness check")
        return {"missing_fields_count": 25, "correctness_score": 0.0}

    cmd = (
        f"python evaluation/scripts/check_completeness.py "
        f"--server {server} --tf-dir {tf_dir} --docker-dir {docker_dir} "
        f'--ci-yaml "{ci_yaml}" --branch {branch}'
    )
    exit_code, output = run_cmd(cmd, f"Running completeness check for {server}...")

    # Parse correctness_score from output
    missing = 0
    score = 1.0
    for line in output.split("\n"):
        if "missing_fields_count" in line and "=" in line:
            try:
                missing = int(line.split("=")[1].strip())
            except (ValueError, IndexError):
                pass
        if "correctness_score" in line and "=" in line and "max" not in line:
            try:
                score = float(line.split("=")[1].strip())
            except (ValueError, IndexError):
                pass

    return {"missing_fields_count": missing, "correctness_score": score}


# =============================================================================
# Main experiment runner
# =============================================================================

def run_single_experiment(
    server: str, approach: str, phase: str,
    ec2_ip: str, pem_path: str, dry_run: bool = False
) -> dict:
    """Run one complete experiment and return the results row."""

    run_num = get_run_count(server, approach, phase) + 1
    run_id = f"{server}-{approach}-{phase[0]}-{run_num:03d}"
    timestamp_start = datetime.now(timezone.utc).isoformat()

    print(f"\n{'='*60}")
    print(f"  EXPERIMENT: {run_id}")
    print(f"  Server: {server} | Approach: {approach} | Phase: {phase}")
    print(f"  Started: {timestamp_start}")
    print(f"{'='*60}")

    if dry_run:
        print("\n  [DRY RUN] Would execute steps 1-5. Exiting.")
        return {}

    row = {
        "run_id": run_id,
        "timestamp_start": timestamp_start,
        "server": server,
        "approach": approach,
        "phase": phase,
        "syntax_errors_count": 0,
        "wrong_config_count": 0,
        "manual_edits_lines": 0,
        "rollback_triggered": 0,
        "failure_category": "",
        "prompts_to_fix": "",
        "edit_span_lines": "",
        "time_to_adapt_secs": "",
        "adaptation_success": "",
        "notes": "",
    }

    total_start = time.perf_counter()

    # Step 1: Generation (LLM only)
    if approach == "llm":
        gen_result = step_generate_llm(server, run_id)
        row["t_gen_secs"] = gen_result["t_gen_secs"]
        row["t_author_secs"] = 0
        row["tokens_prompt"] = gen_result["tokens_prompt"]
        row["tokens_completion"] = gen_result["tokens_completion"]
        row["tokens_total"] = gen_result["tokens_total"]
        row["llm_cost_eur"] = round(gen_result["tokens_total"] / 1000 * 0.002, 4)
    else:
        row["t_gen_secs"] = 0
        row["t_author_secs"] = 22  # Your measured manual authoring time
        row["tokens_prompt"] = 0
        row["tokens_completion"] = 0
        row["tokens_total"] = 0
        row["llm_cost_eur"] = 0

    # Step 2: Deploy
    attempts = 0
    deploy_success = False
    for attempt in range(1, 4):
        attempts = attempt
        try:
            deploy_result = step_deploy(ec2_ip, pem_path, approach, server)
            row["t_pipeline_secs"] = deploy_result["t_pipeline_secs"]
            deploy_success = True
            break
        except Exception as e:
            print(f"  Deploy attempt {attempt} failed: {e}")
            if attempt < 3:
                print("  Retrying in 10 seconds...")
                time.sleep(10)

    row["attempts"] = attempts

    if not deploy_success:
        row["success"] = 0
        row["health_endpoint_pass"] = 0
        row["functional_endpoint_pass"] = 0
        row["failure_category"] = "runtime_error"
        row["t_pipeline_secs"] = row.get("t_pipeline_secs", 0)
        row["t_total_secs"] = round(time.perf_counter() - total_start, 1)
        row["timestamp_end"] = datetime.now(timezone.utc).isoformat()
        append_row(row)
        return row

    # Step 3: Health checks
    health_result = step_health_check(ec2_ip)
    row["health_endpoint_pass"] = health_result["health_endpoint_pass"]

    # Step 4: Functional tests
    if health_result["health_endpoint_pass"]:
        func_result = step_functional_test(ec2_ip)
        row["functional_endpoint_pass"] = func_result["functional_endpoint_pass"]
    else:
        row["functional_endpoint_pass"] = 0

    # Step 5: Completeness check
    comp_result = step_completeness_check(server, approach)
    row["missing_fields_count"] = comp_result.get("missing_fields_count", 0)
    row["correctness_score"] = comp_result.get("correctness_score", 0)

    # Compute derived values
    row["success"] = 1 if (row["health_endpoint_pass"] == 1 and row["functional_endpoint_pass"] == 1) else 0
    row["t_total_secs"] = round(
        (row.get("t_gen_secs") or 0) +
        (row.get("t_author_secs") or 0) +
        (row.get("t_pipeline_secs") or 0),
        1
    )

    # Cost estimation
    pipeline_mins = (row.get("t_pipeline_secs") or 0) / 60
    row["aws_runtime_mins"] = round(pipeline_mins, 1)
    row["aws_cost_eur"] = round(pipeline_mins / 60 * 0.0116, 4)
    row["total_cost_eur"] = round((row.get("aws_cost_eur") or 0) + (row.get("llm_cost_eur") or 0), 4)

    row["timestamp_end"] = datetime.now(timezone.utc).isoformat()

    if row["success"] == 0 and not row["failure_category"]:
        if row["health_endpoint_pass"] == 0:
            row["failure_category"] = "timeout"
        else:
            row["failure_category"] = "runtime_error"

    # Write to CSV
    append_row(row)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT COMPLETE: {run_id}")
    print(f"{'='*60}")
    print(f"  Success:           {'YES' if row['success'] else 'NO'}")
    print(f"  Correctness:       {row['correctness_score']}")
    print(f"  Total time:        {row['t_total_secs']}s")
    print(f"  Pipeline time:     {row['t_pipeline_secs']}s")
    if approach == "llm":
        print(f"  Generation time:   {row['t_gen_secs']}s")
        print(f"  Tokens used:       {row['tokens_total']}")
        print(f"  LLM cost:          EUR {row['llm_cost_eur']}")
    print(f"  AWS cost:          EUR {row['aws_cost_eur']}")
    print(f"  Total cost:        EUR {row['total_cost_eur']}")
    print(f"  Attempts:          {row['attempts']}")
    print(f"  Row written to:    {RESULTS_CSV}")
    print()

    return row


def main():
    parser = argparse.ArgumentParser(description="Run a single experiment cycle")
    parser.add_argument("--server", choices=["jira", "github"])
    parser.add_argument("--approach", choices=["manual", "llm"])
    parser.add_argument("--phase", choices=["A_initial", "B_change"], default="A_initial")
    parser.add_argument("--ec2-ip", default=os.getenv("EC2_IP", ""))
    parser.add_argument("--pem-path", default=os.getenv("PEM_PATH", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all-phase-a", action="store_true",
                        help="Run all 4 Phase A combinations (jira+github × manual+llm)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Number of times to repeat each experiment")

    args = parser.parse_args()

    # Validate environment
    ec2_ip = args.ec2_ip or os.getenv("EC2_IP", "")
    pem_path = args.pem_path or os.getenv("PEM_PATH", "")

    if not ec2_ip:
        print("ERROR: EC2_IP not set. Use --ec2-ip or export EC2_IP=...")
        sys.exit(1)
    if not pem_path:
        print("ERROR: PEM_PATH not set. Use --pem-path or export PEM_PATH=...")
        sys.exit(1)

    ensure_csv_exists()

    if args.all_phase_a:
        combinations = [
            ("jira", "manual"), ("jira", "llm"),
            ("github", "manual"), ("github", "llm"),
        ]
        for server, approach in combinations:
            for _ in range(args.repeat):
                run_single_experiment(
                    server=server, approach=approach, phase="A_initial",
                    ec2_ip=ec2_ip, pem_path=pem_path, dry_run=args.dry_run
                )
    else:
        if not args.server or not args.approach:
            print("ERROR: --server and --approach required (or use --all-phase-a)")
            sys.exit(1)
        for _ in range(args.repeat):
            run_single_experiment(
                server=args.server, approach=args.approach, phase=args.phase,
                ec2_ip=ec2_ip, pem_path=pem_path, dry_run=args.dry_run
            )


if __name__ == "__main__":
    main()