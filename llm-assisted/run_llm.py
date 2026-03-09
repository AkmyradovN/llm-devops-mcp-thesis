#!/usr/bin/env python3
"""
LLM Artefact Generation for MCP Server Deployment

Calls GPT-3.5 Turbo to generate DevOps artefacts (Terraform, Docker, CI/CD)
using structured JSON output. Records timing, token usage, and saves results
for reproducibility and evaluation.

Usage:
    # Generate Terraform for Jira server
    python run_llm.py --artefact terraform --server jira

    # Generate Docker files for GitHub server
    python run_llm.py --artefact docker --server github

    # Generate CI/CD workflow
    python run_llm.py --artefact ci --server both

    # Generate all artefacts for both servers
    python run_llm.py --artefact all --server both

    # Retry with error context (self-correction)
    python run_llm.py --artefact terraform --server jira --error-context "Missing provider block"

"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai package not installed. Run: pip install openai")
    sys.exit(1)

try:
    import jsonschema
except ImportError:
    print("WARNING: jsonschema not installed. Schema validation will be skipped.")
    print("Install with: pip install jsonschema")
    jsonschema = None

# =============================================================================
# Configuration
# =============================================================================

# Paths (relative to repo root)
PROMPTS_DIR = Path("llm-assisted/prompts")
SCHEMAS_DIR = Path("llm-assisted/schemas")
OUTPUT_DIR = Path("llm-assisted/generated")
LOG_DIR = Path("logs")

# LLM settings
MODEL = "gpt-3.5-turbo"
TEMPERATURE = 0.2           # Low temperature for deterministic output
MAX_TOKENS = 4096
MAX_RETRIES = 3             # Max prompt rounds for self-correction

# Server-specific parameters
SERVER_CONFIGS = {
    "jira": {
        "server_name": "MCP-Jira",
        "service_name": "MCP-Jira",
        "host_port": 80,
        "api_version": "v1",
        "functional_endpoints_description": (
            "GET /create_ticket — accepts query params: project (str, required), "
            "summary (str, required), description (str, optional, default ''), "
            "priority (str, optional, default 'Medium', valid: Low/Medium/High/Critical). "
            "Returns a simulated Jira ticket with key, project, summary, description, priority, created timestamp.\n"
            "  GET /get_ticket — accepts query param: ticket_key (str, required). "
            "Returns a simulated ticket object.\n"
            "  GET /list_tickets — accepts query params: project (str, required), "
            "status (str, optional, default 'Open'), max_results (int, optional, default 10, range 1-50). "
            "Returns a list of simulated tickets."
        ),
    },
    "github": {
        "server_name": "MCP-GitHub",
        "service_name": "MCP-GitHub",
        "host_port": 81,
        "api_version": "v1",
        "functional_endpoints_description": (
            "GET /create_issue — accepts query params: owner (str, required), "
            "repo (str, required), title (str, required), body (str, optional, default ''), "
            "labels (str, optional, comma-separated). "
            "Returns a simulated GitHub issue with number, owner, repo, title, body, labels, state, url.\n"
            "  GET /get_issue — accepts query params: owner (str, required), "
            "repo (str, required), issue_number (int, required, >=1). "
            "Returns a simulated issue object.\n"
            "  GET /list_issues — accepts query params: owner (str, required), "
            "repo (str, required), state (str, optional, default 'open', valid: open/closed/all), "
            "max_results (int, optional, default 10, range 1-50). "
            "Returns a list of simulated issues."
        ),
    },
}

# Shared template parameters
SHARED_PARAMS = {
    "region": "eu-central-1",
    "instance_type": "t3.micro",
    "jira_port": 80,
    "github_port": 81,
    "trigger_branch": "llm-assisted",
    "jira_docker_path": "llm-assisted/docker/jira",
    "github_docker_path": "llm-assisted/docker/github",
}

# =============================================================================
# Core Functions
# =============================================================================

def load_prompt(artefact: str, server: str, error_context: str = None) -> str:
    """Load a prompt template and fill in parameters."""
    prompt_file = PROMPTS_DIR / f"prompt_{artefact}.txt"
    if not prompt_file.exists():
        print(f"ERROR: Prompt file not found: {prompt_file}")
        sys.exit(1)

    template = prompt_file.read_text()

    # Merge shared params with server-specific params
    params = {**SHARED_PARAMS}
    if server in SERVER_CONFIGS:
        params.update(SERVER_CONFIGS[server])
    elif server == "both":
        # For CI/CD, use combined params
        params["server_name"] = "MCP-Jira and MCP-GitHub"
        params["service_name"] = "both"
        params["api_version"] = "v1"

    # Fill template
    prompt = template.format(**params)

    # Append error context for self-correction rounds
    if error_context:
        prompt += (
            f"\n\nPREVIOUS ATTEMPT FAILED. Error details:\n{error_context}\n\n"
            "Please fix the issues and regenerate. Return the corrected JSON."
        )

    return prompt

def load_schema(artefact: str) -> dict | None:
    """Load the JSON schema for output validation."""
    schema_file = SCHEMAS_DIR / f"{artefact}.json"
    if schema_file.exists():
        return json.loads(schema_file.read_text())
    return None

def call_llm(prompt: str, run_id: str) -> dict:
    """
    Call GPT-3.5 Turbo with JSON mode and return the parsed response
    along with timing and token metadata.
    """
    client = OpenAI()  # Uses OPENAI_API_KEY env var

    start_time = time.perf_counter()

    response = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a DevOps automation assistant. You MUST respond with "
                    "a single valid JSON object. Do not include any markdown formatting, "
                    "code fences, or explanatory text. Only output the JSON object."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    end_time = time.perf_counter()
    duration = round(end_time - start_time, 3)

    # Extract response
    content = response.choices[0].message.content
    usage = response.usage

    result = {
        "run_id": run_id,
        "model": MODEL,
        "temperature": TEMPERATURE,
        "duration_secs": duration,
        "tokens_prompt": usage.prompt_tokens,
        "tokens_completion": usage.completion_tokens,
        "tokens_total": usage.total_tokens,
        "finish_reason": response.choices[0].finish_reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_content": content,
    }

    # Parse JSON
    try:
        parsed = json.loads(content)
        result["parsed"] = parsed
        result["parse_success"] = True
    except json.JSONDecodeError as e:
        result["parsed"] = None
        result["parse_success"] = False
        result["parse_error"] = str(e)

    return result

def validate_output(parsed: dict, artefact: str) -> list[str]:
    """Validate parsed JSON against the schema. Returns list of errors."""
    if jsonschema is None:
        return []

    schema = load_schema(artefact)
    if schema is None:
        return []

    errors = []
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as e:
        errors.append(str(e.message))
    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")

    return errors

def save_files(parsed: dict, artefact: str, server: str, run_id: str) -> list[str]:
    """Save generated artefact files to disk. Returns list of saved file paths."""
    # Create output directory for this run
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    saved = []

    if artefact == "terraform":
        for key, filename in [
            ("main_tf", "main.tf"),
            ("variables_tf", "variables.tf"),
            ("outputs_tf", "outputs.tf"),
        ]:
            if key in parsed:
                path = run_dir / filename
                path.write_text(parsed[key])
                saved.append(str(path))

    elif artefact == "docker":
        server_dir = run_dir / server
        server_dir.mkdir(parents=True, exist_ok=True)
        for key, filename in [
            ("dockerfile", "Dockerfile"),
            ("app_py", "app.py"),
            ("requirements_txt", "requirements.txt"),
        ]:
            if key in parsed:
                path = server_dir / filename
                path.write_text(parsed[key])
                saved.append(str(path))

    elif artefact == "ci":
        path = run_dir / "deploy.yml"
        if "deploy_yml" in parsed:
            path.write_text(parsed["deploy_yml"])
            saved.append(str(path))

    return saved

def save_log(result: dict, artefact: str, server: str, run_id: str):
    """Save the full generation log (prompt, response, timing, tokens) to JSON."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{run_id}_{artefact}_{server}.json"

    # Don't save the raw content twice if parsed succeeded
    log_data = {k: v for k, v in result.items() if k != "raw_content"}
    log_data["raw_content_length"] = len(result.get("raw_content", ""))

    log_file.write_text(json.dumps(log_data, indent=2, default=str))
    return str(log_file)

# =============================================================================
# Main
# =============================================================================

def run_generation(artefact: str, server: str, error_context: str = None):
    """Run a single generation cycle for one artefact type."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{server}-{artefact}-{timestamp}"

    print(f"\n{'='*60}")
    print(f"  Generating: {artefact} | Server: {server} | Run: {run_id}")
    print(f"  Model: {MODEL} | Temperature: {TEMPERATURE}")
    print(f"{'='*60}\n")

    # Step 1: Load prompt
    prompt = load_prompt(artefact, server, error_context)
    print(f"[1/5] Prompt loaded ({len(prompt)} chars)")

    # Step 2: Call LLM
    print(f"[2/5] Calling {MODEL}...")
    result = call_llm(prompt, run_id)
    print(f"      Duration: {result['duration_secs']}s")
    print(f"      Tokens:   {result['tokens_prompt']} prompt + "
          f"{result['tokens_completion']} completion = {result['tokens_total']} total")
    print(f"      Finish:   {result['finish_reason']}")

    if not result["parse_success"]:
        print(f"\n  ERROR: Failed to parse JSON response")
        print(f"  Parse error: {result.get('parse_error', 'unknown')}")
        log_path = save_log(result, artefact, server, run_id)
        print(f"  Log saved: {log_path}")
        return result

    print(f"[3/5] JSON parsed successfully")

    # Step 3: Validate against schema
    errors = validate_output(result["parsed"], artefact)
    if errors:
        print(f"\n  VALIDATION ERRORS:")
        for err in errors:
            print(f"    - {err}")
        result["validation_errors"] = errors
    else:
        print(f"[4/5] Schema validation passed")
        result["validation_errors"] = []

    # Step 4: Save files
    saved = save_files(result["parsed"], artefact, server, run_id)
    print(f"[5/5] Files saved:")
    for f in saved:
        print(f"      {f}")

    # Step 5: Save log
    log_path = save_log(result, artefact, server, run_id)
    print(f"      Log: {log_path}")

    # Summary
    print(f"\n{'─'*60}")
    print(f"  RESULT: {'SUCCESS' if not errors else 'GENERATED WITH VALIDATION ERRORS'}")
    print(f"  Run ID:     {run_id}")
    print(f"  Duration:   {result['duration_secs']}s")
    print(f"  Tokens:     {result['tokens_total']}")
    print(f"  Cost (est): ${result['tokens_total'] / 1000 * 0.002:.4f}")
    print(f"{'─'*60}\n")

    return result

def run_with_retries(artefact: str, server: str, max_retries: int = MAX_RETRIES):
    """Run generation with self-correction retries on failure."""
    error_context = None

    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print(f"\n>>> RETRY {attempt}/{max_retries} (self-correction) <<<\n")

        result = run_generation(artefact, server, error_context)

        # Check if successful
        if (result.get("parse_success") and
                not result.get("validation_errors")):
            result["total_attempts"] = attempt
            return result

        # Build error context for next attempt
        errors = []
        if not result.get("parse_success"):
            errors.append(f"JSON parse error: {result.get('parse_error')}")
        if result.get("validation_errors"):
            errors.extend(result["validation_errors"])
        error_context = "\n".join(errors)

    print(f"\nFAILED after {max_retries} attempts.")
    result["total_attempts"] = max_retries
    return result

def main():
    parser = argparse.ArgumentParser(
        description="Generate DevOps artefacts using GPT-3.5 Turbo"
    )
    parser.add_argument(
        "--artefact",
        choices=["terraform", "docker", "ci", "all"],
        required=True,
        help="Type of artefact to generate",
    )
    parser.add_argument(
        "--server",
        choices=["jira", "github", "both"],
        required=True,
        help="Target MCP server",
    )
    parser.add_argument(
        "--error-context",
        default=None,
        help="Error context from a previous failed attempt (for manual retry)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=MAX_RETRIES,
        help=f"Maximum retry attempts (default: {MAX_RETRIES})",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="Disable automatic retries",
    )

    args = parser.parse_args()

    # Verify API key
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-key-here'")
        sys.exit(1)

    max_retries = 1 if args.no_retry else args.max_retries

    # Determine what to generate
    if args.artefact == "all":
        artefacts = ["terraform", "docker", "ci"]
    else:
        artefacts = [args.artefact]

    if args.server == "both" and "docker" in artefacts:
        servers_for_docker = ["jira", "github"]
    else:
        servers_for_docker = [args.server]

    # Track totals
    total_tokens = 0
    total_duration = 0.0
    total_attempts = 0
    all_results = []

    for artefact in artefacts:
        if artefact == "docker":
            for server in servers_for_docker:
                result = run_with_retries(artefact, server, max_retries)
                all_results.append(result)
                total_tokens += result.get("tokens_total", 0)
                total_duration += result.get("duration_secs", 0)
                total_attempts += result.get("total_attempts", 1)
        else:
            server = args.server if artefact != "ci" else "both"
            result = run_with_retries(artefact, server, max_retries)
            all_results.append(result)
            total_tokens += result.get("tokens_total", 0)
            total_duration += result.get("duration_secs", 0)
            total_attempts += result.get("total_attempts", 1)

    # Final summary
    print(f"\n{'='*60}")
    print(f"  GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Artefacts:      {', '.join(artefacts)}")
    print(f"  Total duration: {total_duration:.1f}s")
    print(f"  Total tokens:   {total_tokens}")
    print(f"  Total attempts: {total_attempts}")
    print(f"  Est. cost:      ${total_tokens / 1000 * 0.002:.4f}")
    print(f"{'='*60}")
    print(f"\n>> For results.csv:")
    print(f"   t_gen_secs       = {total_duration:.1f}")
    print(f"   tokens_prompt    = {sum(r.get('tokens_prompt', 0) for r in all_results)}")
    print(f"   tokens_completion = {sum(r.get('tokens_completion', 0) for r in all_results)}")
    print(f"   tokens_total     = {total_tokens}")
    print(f"   llm_cost_eur     = {total_tokens / 1000 * 0.002:.4f}")

if __name__ == "__main__":
    main()