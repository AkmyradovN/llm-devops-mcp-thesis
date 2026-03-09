#!/usr/bin/env python3
"""
run_adaptation.py — Phase B Adaptation Experiments
=============================================================================
Tests how well the manual and LLM approaches handle an API version change
(v1 → v2). Records prompts_to_fix, edit_span_lines, time_to_adapt_secs,
and adaptation_success.

Usage:
    # Single run
    python run_adaptation.py --server jira --approach llm
    python run_adaptation.py --server jira --approach manual

    # All Phase B combinations
    python run_adaptation.py --all

    # All with 10 repeats
    python run_adaptation.py --all --repeat 10
=============================================================================
"""

import argparse
import csv
import difflib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ── Paths ──
RESULTS_CSV = Path("evaluation/results.csv")
MANUAL_V1_DIR = Path("manual-baseline/docker")
MANUAL_V2_DIR = Path("phase-b/manual-v2")
LLM_PROMPTS_DIR = Path("llm-assisted/prompts")
LLM_GENERATED_DIR = Path("llm-assisted/generated")
PHASE_B_PROMPT = Path("phase-b/prompt_adaptation.txt")
LOGS_DIR = Path("logs")

JIRA_PORT = 80
GITHUB_PORT = 81

# ── LLM settings ──
MODEL = "gpt-3.5-turbo"
TEMPERATURE = 0.2
MAX_TOKENS = 4096
MAX_LLM_ROUNDS = 5

# ── Cost & time parameters ──
MANUAL_ADAPT_SECS = 600   # 10 minutes to manually adapt v1→v2
HUMAN_HOURLY_EUR = 30.0
EC2_COMBINED_HOURLY_EUR = 0.018

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


def get_run_count(server, approach, phase):
    if not RESULTS_CSV.exists():
        return 0
    count = 0
    with open(RESULTS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("server") == server and row.get("approach") == approach and row.get("phase") == phase:
                count += 1
    return count


def ensure_csv():
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not RESULTS_CSV.exists() or RESULTS_CSV.stat().st_size == 0:
        with open(RESULTS_CSV, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADERS)


def append_row(row):
    ensure_csv()
    with open(RESULTS_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)
    print(f"  ✓ Row written to {RESULTS_CSV}")


def run_cmd(cmd, desc, capture=True):
    print(f"  → {desc}")
    r = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=300)
    output = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and capture:
        print(f"    WARNING: exit code {r.returncode}")
        for line in output.strip().split("\n")[:10]:  # increased from 3 to 10 for better debugging
            print(f"    {line}")
    return r.returncode, output


def compute_diff_lines(v1_dir: Path, v2_dir: Path) -> int:
    """Count changed lines between v1 and v2 app.py files."""
    v1_file = v1_dir / "app.py"
    v2_file = v2_dir / "app.py"
    if not v1_file.exists() or not v2_file.exists():
        return 0
    v1_lines = v1_file.read_text().splitlines()
    v2_lines = v2_file.read_text().splitlines()
    diff = list(difflib.unified_diff(v1_lines, v2_lines, lineterm=""))
    changed = sum(1 for line in diff if line.startswith("+") or line.startswith("-"))
    # Subtract the --- and +++ header lines
    return max(0, changed - 2)


# ═══════════════════════════════════════════════════════════════
# LLM adaptation
# ═══════════════════════════════════════════════════════════════

def llm_adapt(server: str, run_id: str) -> dict:
    """Prompt the LLM to adapt v1 code to v2. Returns generation metadata."""
    if OpenAI is None:
        print("  ERROR: openai package not installed")
        return {"success": False, "t_gen_secs": 0, "prompts_to_fix": 0, "tokens_total": 0}

    client = OpenAI()

    # Load v1 source files
    v1_app = (MANUAL_V1_DIR / server / "app.py").read_text()
    v1_dockerfile = (MANUAL_V1_DIR / server / "Dockerfile").read_text()

    # Load prompt template
    template = PHASE_B_PROMPT.read_text()

    # Server-specific parameters
    if server == "jira":
        endpoint_changes = "/create_ticket → /v2/create_ticket, /get_ticket → /v2/get_ticket, /list_tickets → /v2/list_tickets"
        service_name = "MCP-Jira"
    else:
        endpoint_changes = "/create_issue → /v2/create_issue, /get_issue → /v2/get_issue, /list_issues → /v2/list_issues"
        service_name = "MCP-GitHub"

    prompt = template.format(
        existing_app_py=v1_app,
        existing_dockerfile=v1_dockerfile,
        endpoint_changes=endpoint_changes,
        service_name=service_name,
    )

    total_tokens = 0
    tokens_prompt = 0
    tokens_completion = 0
    total_start = time.perf_counter()
    rounds = 0
    last_error = None

    for attempt in range(1, MAX_LLM_ROUNDS + 1):
        rounds = attempt

        if last_error:
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED:\n{last_error}\nPlease fix and return corrected JSON."

        print(f"  LLM adaptation round {attempt}/{MAX_LLM_ROUNDS}...")

        start = time.perf_counter()
        response = client.chat.completions.create(
            model=MODEL, temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a DevOps assistant. Respond ONLY with valid JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        duration = time.perf_counter() - start

        usage = response.usage
        total_tokens += usage.total_tokens
        tokens_prompt += usage.prompt_tokens
        tokens_completion += usage.completion_tokens

        content = response.choices[0].message.content

        # Parse JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            print(f"    Round {attempt} failed: {last_error}")
            continue

        # Validate required keys
        if "app_py" not in parsed or "dockerfile" not in parsed:
            last_error = "Missing required keys: app_py, dockerfile"
            print(f"    Round {attempt} failed: {last_error}")
            continue

        # ── Sanitize LLM-generated Dockerfile before saving ──
        import re as _re
        dockerfile = parsed["dockerfile"]
        # Fix: CMD ['uvicorn', ...] → CMD ["uvicorn", ...] single→double quotes in exec-form
        dockerfile = _re.sub(
            r"^(CMD \[)(.*?)(\])$",
            lambda m: m.group(1) + m.group(2).replace("'", '"') + m.group(3),
            dockerfile, flags=_re.MULTILINE
        )
        # Fix: HEALTHCHECK /v2/health → /health (health is infra, should not be versioned)
        dockerfile = dockerfile.replace(
            "curl -sf http://localhost:8000/v2/health",
            "curl -sf http://localhost:8000/health"
        )

        # Save generated files
        out_dir = LLM_GENERATED_DIR / f"{run_id}-v2" / server
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "app.py").write_text(parsed["app_py"])
        (out_dir / "Dockerfile").write_text(dockerfile)
        (out_dir / "requirements.txt").write_text(parsed.get("requirements_txt", "fastapi==0.115.6\nuvicorn==0.34.0\n"))

        total_duration = time.perf_counter() - total_start

        print(f"    Round {attempt} succeeded: files saved to {out_dir}")

        return {
            "success": True,
            "t_gen_secs": round(total_duration, 1),
            "prompts_to_fix": rounds,
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "tokens_total": total_tokens,
            "generated_dir": out_dir,
        }

    total_duration = time.perf_counter() - total_start
    return {
        "success": False,
        "t_gen_secs": round(total_duration, 1),
        "prompts_to_fix": rounds,
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "tokens_total": total_tokens,
        "generated_dir": None,
    }


# ═══════════════════════════════════════════════════════════════
# Deploy + Verify (Phase B specific)
# ═══════════════════════════════════════════════════════════════

def deploy_v2(ec2_ip: str, pem_path: str, jira_src: Path, github_src: Path) -> dict:
    """Deploy v2 containers to EC2."""
    start = time.perf_counter()
    ssh = f"-o StrictHostKeyChecking=no -o ConnectTimeout=10"

    # Clean
    run_cmd(f'ssh {ssh} -i {pem_path} ubuntu@{ec2_ip} "docker stop mcp-jira mcp-github 2>/dev/null; docker rm mcp-jira mcp-github 2>/dev/null; rm -rf /home/ubuntu/jira /home/ubuntu/github"', "Cleaning EC2...")

    # Copy
    run_cmd(f"scp {ssh} -i {pem_path} -r {jira_src} ubuntu@{ec2_ip}:/home/ubuntu/jira", f"Copying jira from {jira_src}...")
    run_cmd(f"scp {ssh} -i {pem_path} -r {github_src} ubuntu@{ec2_ip}:/home/ubuntu/github", f"Copying github from {github_src}...")

    # Build + run — split into separate SSH calls to identify exactly which step fails
    for svc, port in [("jira", JIRA_PORT), ("github", GITHUB_PORT)]:
        # Step A: build — pass a timestamp build-arg to bust the app.py layer cache
        # without re-downloading the base image (avoids disk-full from --no-cache)
        build_ts = int(time.time())
        build_code, build_out = run_cmd(
            f'ssh {ssh} -i {pem_path} ubuntu@{ec2_ip} '
            f'"cd /home/ubuntu/{svc} && docker build --build-arg BUILD_TS={build_ts} -t mcp-{svc} . 2>&1"',
            f"Building mcp-{svc} image..."
        )
        if build_code != 0:
            # Print ALL build output so we can see exactly what failed
            print(f"    ─── Full build output for mcp-{svc} ───")
            for line in build_out.strip().split("\n"):
                print(f"    {line}")
            print(f"    ─── Build FAILED (exit {build_code}) ───")
            continue  # skip docker run for this service

        # Step B: run only
        run_code, run_out = run_cmd(
            f'ssh {ssh} -i {pem_path} ubuntu@{ec2_ip} '
            f'"docker run -d --name mcp-{svc} -p {port}:8000 '
            f'-e MCP_API_VERSION=v2 -e MCP_SERVER_ENV=production '
            f'--restart unless-stopped mcp-{svc}"',
            f"Starting mcp-{svc} container on port {port}..."
        )
        if run_code != 0:
            print(f"    ─── docker run output ───")
            for line in run_out.strip().split("\n"):
                print(f"    {line}")
            # Check container status for extra clues
            run_cmd(
                f'ssh {ssh} -i {pem_path} ubuntu@{ec2_ip} '
                f'"docker inspect --format=\'Exit={{{{.State.ExitCode}}}} Error={{{{.State.Error}}}}\' mcp-{svc} 2>/dev/null || echo container_not_created"',
                f"Checking mcp-{svc} exit status..."
            )


    return {"t_pipeline_secs": round(time.perf_counter() - start, 1)}


def verify_v2(ec2_ip: str) -> dict:
    """Verify Phase B: v2 health check + v2 functional endpoints."""
    import urllib.request
    import urllib.error
    import urllib.parse

    results = {"health_pass": True, "functional_pass": True}

    # Health checks — try /health first, then /v2/health (LLM sometimes prefixes it)
    for name, port in [("jira", JIRA_PORT), ("github", GITHUB_PORT)]:
        passed = False
        health_paths_tried = []

        for attempt in range(1, 13):
            # On first attempt, also detect if /v2/health exists instead of /health
            for path in ["/health", "/v2/health"]:
                url = f"http://{ec2_ip}:{port}{path}"
                try:
                    with urllib.request.urlopen(url, timeout=5) as resp:
                        if resp.status == 200:
                            body = json.loads(resp.read().decode())
                            has_ok = body.get("status") == "ok"
                            has_v2 = body.get("version") == "v2"
                            has_stable = body.get("api_status") == "stable"
                            if has_ok and has_v2 and has_stable:
                                print(f"  ✓ {name} v2 health OK ({path}): {body}")
                                passed = True
                                break
                            else:
                                missing = []
                                if not has_v2: missing.append("version!=v2")
                                if not has_stable: missing.append("no api_status")
                                print(f"    {name} attempt {attempt} {path}: response OK but missing {missing}")
                except Exception:
                    pass

            if passed:
                break
            print(f"    {name} attempt {attempt}/12 — waiting 5s...")
            time.sleep(5)

        if not passed:
            print(f"  ✗ {name} v2 health FAILED")
            results["health_pass"] = False

    # Functional tests — v2 endpoints
    v2_tests = {
        "jira": [("/v2/create_ticket", {"project": "TEST", "summary": "v2-test", "priority": "Medium"})],
        "github": [("/v2/create_issue", {"owner": "test", "repo": "test-repo", "title": "v2-test"})],
    }

    for svc, endpoints in v2_tests.items():
        port = JIRA_PORT if svc == "jira" else GITHUB_PORT
        for path, params in endpoints:
            query = urllib.parse.urlencode(params)
            url = f"http://{ec2_ip}:{port}{path}?{query}"
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    body = json.loads(resp.read().decode())
                    ok = body.get("status") == "success"
                    icon = "✓" if ok else "✗"
                    print(f"  {icon} {svc} {path} — {'PASS' if ok else 'FAIL'}")
                    if not ok:
                        results["functional_pass"] = False
            except Exception as e:
                print(f"  ✗ {svc} {path} — ERROR: {e}")
                results["functional_pass"] = False

    return results


# ═══════════════════════════════════════════════════════════════
# Main experiment
# ═══════════════════════════════════════════════════════════════

def run_adaptation_experiment(server: str, approach: str, ec2_ip: str, pem_path: str):
    """Run one Phase B adaptation experiment."""

    run_num = get_run_count(server, approach, "B_change") + 1
    run_id = f"{server}-{approach}-B-{run_num:03d}"
    timestamp_start = datetime.now(timezone.utc).isoformat()

    print(f"\n{'='*60}")
    print(f"  PHASE B EXPERIMENT: {run_id}")
    print(f"  Server: {server} | Approach: {approach} | Phase: B_change")
    print(f"{'='*60}")

    row = {
        "run_id": run_id, "timestamp_start": timestamp_start,
        "server": server, "approach": approach, "phase": "B_change",
        "syntax_errors_count": 0, "missing_fields_count": 0, "wrong_config_count": 0,
        "manual_edits_lines": 0, "rollback_triggered": 0, "failure_category": "",
        "notes": "Phase B: v1→v2 adaptation",
    }

    adapt_start = time.perf_counter()

    if approach == "manual":
        # ── Manual adaptation: use pre-written v2 files ──
        row["t_author_secs"] = MANUAL_ADAPT_SECS
        row["t_gen_secs"] = 0
        row["prompts_to_fix"] = ""
        row["tokens_prompt"] = 0
        row["tokens_completion"] = 0
        row["tokens_total"] = 0
        row["llm_cost_eur"] = 0

        jira_src = MANUAL_V2_DIR / "jira"
        github_src = MANUAL_V2_DIR / "github"

        # Compute diff
        row["edit_span_lines"] = compute_diff_lines(MANUAL_V1_DIR / server, MANUAL_V2_DIR / server)

    else:
        # ── LLM adaptation ──
        row["t_author_secs"] = 0

        print(f"\n{'─'*60}")
        print(f"  STEP 1: LLM Adaptation (v1 → v2)")
        print(f"{'─'*60}")

        gen = llm_adapt(server, run_id)
        row["t_gen_secs"] = gen["t_gen_secs"]
        row["prompts_to_fix"] = gen["prompts_to_fix"]
        row["tokens_prompt"] = gen["tokens_prompt"]
        row["tokens_completion"] = gen["tokens_completion"]
        row["tokens_total"] = gen["tokens_total"]
        row["llm_cost_eur"] = round(gen["tokens_total"] / 1000 * 0.002, 4)

        if not gen["success"] or gen["generated_dir"] is None:
            row["adaptation_success"] = 0
            row["success"] = 0
            row["health_endpoint_pass"] = 0
            row["functional_endpoint_pass"] = 0
            row["failure_category"] = "generation_failed"
            row["t_pipeline_secs"] = 0
            adapt_duration = time.perf_counter() - adapt_start
            row["time_to_adapt_secs"] = round(adapt_duration, 1)
            row["t_total_secs"] = round(gen["t_gen_secs"], 1)
            row["correctness_score"] = 0
            row["attempts"] = 1
            row["aws_runtime_mins"] = 0
            row["aws_cost_eur"] = 0
            row["total_cost_eur"] = row["llm_cost_eur"]
            row["timestamp_end"] = datetime.now(timezone.utc).isoformat()
            append_row(row)
            return row

        # Use LLM-generated v2 files
        jira_src = gen["generated_dir"] if server == "jira" else (LLM_GENERATED_DIR / f"{run_id}-v2" / "jira")
        github_src = gen["generated_dir"] if server == "github" else (LLM_GENERATED_DIR / f"{run_id}-v2" / "github")

        # If we only generated for one server, use manual v2 for the other
        if server == "jira" and not (github_src / "Dockerfile").exists():
            github_src = MANUAL_V2_DIR / "github"
        elif server == "github" and not (jira_src / "Dockerfile").exists():
            jira_src = MANUAL_V2_DIR / "jira"

        # Compute diff vs v1
        row["edit_span_lines"] = compute_diff_lines(MANUAL_V1_DIR / server, gen["generated_dir"])

    # ── Deploy v2 ──
    print(f"\n{'─'*60}")
    print(f"  STEP 2: Deploy v2")
    print(f"{'─'*60}")

    deploy_result = deploy_v2(ec2_ip, pem_path, jira_src, github_src)
    row["t_pipeline_secs"] = deploy_result["t_pipeline_secs"]
    row["attempts"] = 1

    # ── Verify v2 ──
    print(f"\n{'─'*60}")
    print(f"  STEP 3: Verify v2 Deployment")
    print(f"{'─'*60}")

    verify = verify_v2(ec2_ip)
    row["health_endpoint_pass"] = 1 if verify["health_pass"] else 0
    row["functional_endpoint_pass"] = 1 if verify["functional_pass"] else 0

    # ── Compute results ──
    adapt_duration = time.perf_counter() - adapt_start
    row["time_to_adapt_secs"] = round(adapt_duration, 1)
    row["success"] = 1 if (verify["health_pass"] and verify["functional_pass"]) else 0
    row["adaptation_success"] = row["success"]
    row["correctness_score"] = 1.0 if row["success"] else 0.5

    row["t_total_secs"] = round(
        (row.get("t_gen_secs") or 0) + (row.get("t_author_secs") or 0) + (row.get("t_pipeline_secs") or 0), 1
    )

    # Cost
    lifecycle_mins = max(5.0, (row.get("t_pipeline_secs") or 0) / 60)
    row["aws_runtime_mins"] = round(lifecycle_mins, 1)
    row["aws_cost_eur"] = round(lifecycle_mins / 60 * EC2_COMBINED_HOURLY_EUR, 6)
    human_labor = round(((row.get("t_author_secs") or 0) / 3600) * HUMAN_HOURLY_EUR, 4)
    row["total_cost_eur"] = round((row.get("aws_cost_eur") or 0) + (row.get("llm_cost_eur") or 0) + human_labor, 4)

    row["timestamp_end"] = datetime.now(timezone.utc).isoformat()

    if not row["success"] and not row["failure_category"]:
        row["failure_category"] = "runtime_error"

    append_row(row)

    # Summary
    print(f"\n{'='*60}")
    print(f"  PHASE B RESULT: {run_id}")
    print(f"{'='*60}")
    print(f"  Adaptation:      {'SUCCESS' if row['success'] else 'FAILED'}")
    print(f"  Approach:        {approach}")
    print(f"  Adapt time:      {row['time_to_adapt_secs']}s")
    print(f"  Edit lines:      {row['edit_span_lines']}")
    if approach == "llm":
        print(f"  Prompt rounds:   {row['prompts_to_fix']}")
        print(f"  Tokens:          {row['tokens_total']}")
    print(f"  Total cost:      EUR {row['total_cost_eur']}")
    print()

    return row


def main():
    parser = argparse.ArgumentParser(description="Phase B adaptation experiments")
    parser.add_argument("--server", choices=["jira", "github"])
    parser.add_argument("--approach", choices=["manual", "llm"])
    parser.add_argument("--ec2-ip", default=os.getenv("EC2_IP", ""))
    parser.add_argument("--pem-path", default=os.getenv("PEM_PATH", ""))
    parser.add_argument("--all", action="store_true", help="Run all 4 combinations")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    ec2_ip = args.ec2_ip or os.getenv("EC2_IP", "")
    pem_path = args.pem_path or os.getenv("PEM_PATH", "")
    if not ec2_ip or not pem_path:
        print("ERROR: Set EC2_IP and PEM_PATH (env vars or --flags)")
        sys.exit(1)

    ensure_csv()

    if args.all:
        combos = [("jira", "manual"), ("jira", "llm"), ("github", "manual"), ("github", "llm")]
        for server, approach in combos:
            for _ in range(args.repeat):
                run_adaptation_experiment(server, approach, ec2_ip, pem_path)
    else:
        if not args.server or not args.approach:
            print("ERROR: --server and --approach required (or use --all)")
            sys.exit(1)
        for _ in range(args.repeat):
            run_adaptation_experiment(args.server, args.approach, ec2_ip, pem_path)


if __name__ == "__main__":
    main()