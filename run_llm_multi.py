#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from google import genai as genai_new
    from google.genai import types as genai_types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    import jsonschema
except ImportError:
    jsonschema = None


# Configuration

PROMPTS_DIR = Path("llm-assisted/prompts")
SCHEMAS_DIR = Path("llm-assisted/schemas")
OUTPUT_DIR = Path("llm-assisted/generated")
LOG_DIR = Path("logs")

# Model configurations
MODELS = {
    "gpt-3.5-turbo": {
        "provider": "openai",
        "model_id": "gpt-3.5-turbo",
        "display_name": "GPT-3.5 Turbo",
        "temperature": 0.2,
        "max_tokens": 4096,
        "env_key": "OPENAI_API_KEY",
        "cost_per_1k_input": 0.0005,
        "cost_per_1k_output": 0.0015,
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "model_id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "temperature": 0.2,
        "max_tokens": 4096,
        "env_key": "GOOGLE_API_KEY",
        "cost_per_1k_input": 0.0,    # Free tier
        "cost_per_1k_output": 0.0,
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-5-20250929",
        "display_name": "Claude Sonnet 4.5",
        "temperature": 0.2,
        "max_tokens": 4096,
        "env_key": "ANTHROPIC_API_KEY",
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
    },
}

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

SHARED_PARAMS = {
    "region": "eu-central-1",
    "instance_type": "t2.micro",
    "jira_port": 80,
    "github_port": 81,
    "trigger_branch": "llm-assisted",
    "jira_docker_path": "llm-assisted/docker/jira",
    "github_docker_path": "llm-assisted/docker/github",
}


# Provider-specific API calls

def call_openai(prompt: str, model_config: dict) -> dict:
    """Call OpenAI API with JSON mode."""
    client = OpenAI()
    start = time.perf_counter()

    response = client.chat.completions.create(
        model=model_config["model_id"],
        temperature=model_config["temperature"],
        max_tokens=model_config["max_tokens"],
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a DevOps automation assistant. Respond ONLY with a single valid JSON object. No markdown, no explanation."},
            {"role": "user", "content": prompt},
        ],
    )

    duration = time.perf_counter() - start
    usage = response.usage

    return {
        "content": response.choices[0].message.content,
        "duration_secs": round(duration, 3),
        "tokens_prompt": usage.prompt_tokens,
        "tokens_completion": usage.completion_tokens,
        "tokens_total": usage.total_tokens,
        "finish_reason": response.choices[0].finish_reason,
    }


def call_gemini(prompt: str, model_config: dict) -> dict:
    """Call Google Gemini API using the new google.genai SDK."""
    client = genai_new.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    full_prompt = (
        "You are a DevOps automation assistant. Respond ONLY with a single valid JSON object. "
        "No markdown formatting, no code fences, no explanation. Only the JSON object.\n\n"
        + prompt
    )

    config = genai_types.GenerateContentConfig(
        temperature=model_config["temperature"],
        max_output_tokens=model_config["max_tokens"],
        response_mime_type="application/json",
        system_instruction=(
            "You are a DevOps automation assistant. Respond ONLY with a single valid JSON object. "
            "No markdown formatting, no code fences, no explanation. Only the JSON object."
        ),
    )

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            start = time.perf_counter()
            response = client.models.generate_content(
                model=model_config["model_id"],
                contents=full_prompt,
                config=config,
            )
            duration = time.perf_counter() - start
            break
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                import re
                match = re.search(r"retry in ([\d.]+)s", err_str)
                wait = float(match.group(1)) if match else 60.0
                wait = min(wait + 5, 120)  # add buffer, cap at 2 min
                print(f"  Rate limited (attempt {attempt}/{max_retries}). Waiting {wait:.0f}s...")
                if attempt == max_retries:
                    raise
                time.sleep(wait)
            else:
                raise

    # Usage metadata
    usage = response.usage_metadata
    tokens_prompt = usage.prompt_token_count if usage else 0
    tokens_completion = usage.candidates_token_count if usage else 0

    return {
        "content": response.text,
        "duration_secs": round(duration, 3),
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "tokens_total": tokens_prompt + tokens_completion,
        "finish_reason": "stop",
    }


def call_anthropic(prompt: str, model_config: dict) -> dict:
    """Call Anthropic Claude API."""
    client = anthropic.Anthropic()
    start = time.perf_counter()

    response = client.messages.create(
        model=model_config["model_id"],
        max_tokens=model_config["max_tokens"],
        temperature=model_config["temperature"],
        system="You are a DevOps automation assistant. Respond ONLY with a single valid JSON object. No markdown formatting, no code fences, no explanation. Only the JSON object.",
        messages=[{"role": "user", "content": prompt}],
    )

    duration = time.perf_counter() - start

    content = response.content[0].text if response.content else ""

    return {
        "content": content,
        "duration_secs": round(duration, 3),
        "tokens_prompt": response.usage.input_tokens,
        "tokens_completion": response.usage.output_tokens,
        "tokens_total": response.usage.input_tokens + response.usage.output_tokens,
        "finish_reason": response.stop_reason,
    }


def call_llm(prompt: str, model_name: str) -> dict:
    """Route to the correct provider."""
    config = MODELS[model_name]
    provider = config["provider"]

    if provider == "openai":
        if not HAS_OPENAI:
            print("  ERROR: openai package not installed (pip install openai)")
            return None
        return call_openai(prompt, config)
    elif provider == "gemini":
        if not HAS_GEMINI:
            print("  ERROR: google-generativeai package not installed (pip install google-generativeai)")
            return None
        return call_gemini(prompt, config)
    elif provider == "anthropic":
        if not HAS_ANTHROPIC:
            print("  ERROR: anthropic package not installed (pip install anthropic)")
            return None
        return call_anthropic(prompt, config)
    else:
        print(f"  ERROR: Unknown provider {provider}")
        return None


# Prompt loading and file saving

def load_prompt(artefact: str, server: str) -> str:
    prompt_file = PROMPTS_DIR / f"prompt_{artefact}.txt"
    if not prompt_file.exists():
        print(f"ERROR: Prompt file not found: {prompt_file}")
        sys.exit(1)

    template = prompt_file.read_text()
    params = {**SHARED_PARAMS}
    if server in SERVER_CONFIGS:
        params.update(SERVER_CONFIGS[server])
    elif server == "both":
        params["server_name"] = "MCP-Jira and MCP-GitHub"
        params["service_name"] = "both"
        params["api_version"] = "v1"

    return template.format(**params)


def load_schema(artefact: str) -> dict | None:
    schema_file = SCHEMAS_DIR / f"{artefact}.json"
    if schema_file.exists():
        return json.loads(schema_file.read_text())
    return None


def validate_output(parsed: dict, artefact: str) -> list[str]:
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
    return errors


def save_files(parsed: dict, artefact: str, server: str, run_id: str) -> list[str]:
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    if artefact == "terraform":
        for key, filename in [("main_tf", "main.tf"), ("variables_tf", "variables.tf"), ("outputs_tf", "outputs.tf")]:
            if key in parsed:
                path = run_dir / filename
                path.write_text(parsed[key])
                saved.append(str(path))
    elif artefact == "docker":
        server_dir = run_dir / server
        server_dir.mkdir(parents=True, exist_ok=True)
        for key, filename in [("dockerfile", "Dockerfile"), ("app_py", "app.py"), ("requirements_txt", "requirements.txt")]:
            if key in parsed:
                path = server_dir / filename
                path.write_text(parsed[key])
                saved.append(str(path))
    elif artefact == "ci":
        if "deploy_yml" in parsed:
            path = run_dir / "deploy.yml"
            path.write_text(parsed["deploy_yml"])
            saved.append(str(path))

    return saved


def save_log(result: dict, run_id: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{run_id}.json"
    log_data = {k: v for k, v in result.items() if k != "raw_content"}
    log_file.write_text(json.dumps(log_data, indent=2, default=str))
    return str(log_file)

# main generation

def run_generation(artefact: str, server: str, model_name: str) -> dict:
    """Run a single generation for one artefact type with one model."""
    config = MODELS[model_name]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{server}-{artefact}-{model_name}-{timestamp}"

    print(f"\n  {'─'*55}")
    print(f"  {artefact} | {server} | {config['display_name']}")
    print(f"  {'─'*55}")

    prompt = load_prompt(artefact, server)
    print(f"  Prompt: {len(prompt)} chars")

    response = call_llm(prompt, model_name)
    if response is None:
        return {"success": False, "model": model_name, "artefact": artefact, "server": server}

    print(f"  Duration: {response['duration_secs']}s | Tokens: {response['tokens_total']}")

    # Parse JSON
    content = response["content"]
    if content.strip().startswith("```"):
        lines = content.strip().split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        parsed = json.loads(content)
        parse_success = True
    except json.JSONDecodeError as e:
        print(f"  JSON parse FAILED: {e}")
        parse_success = False
        parsed = None

    errors = []
    if parsed:
        errors = validate_output(parsed, artefact)
        if errors:
            print(f"  Validation errors: {errors}")

    # Save files
    saved = []
    if parsed and not errors:
        saved = save_files(parsed, artefact, server, run_id)
        print(f"  Files saved: {len(saved)}")

    result = {
        "success": parse_success and not errors,
        "model": model_name,
        "model_display": config["display_name"],
        "artefact": artefact,
        "server": server,
        "run_id": run_id,
        "duration_secs": response["duration_secs"],
        "tokens_prompt": response["tokens_prompt"],
        "tokens_completion": response["tokens_completion"],
        "tokens_total": response["tokens_total"],
        "parse_success": parse_success,
        "validation_errors": errors,
        "files_saved": saved,
        "cost_usd": round(
            response["tokens_prompt"] / 1000 * config["cost_per_1k_input"] +
            response["tokens_completion"] / 1000 * config["cost_per_1k_output"],
            6
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    save_log(result, run_id)
    return result


def run_full_generation(model_name: str, server_arg: str) -> list[dict]:
    """Generate all artefacts for a given model."""
    results = []

    # Terraform (shared for both servers)
    results.append(run_generation("terraform", server_arg, model_name))

    # Docker (per server)
    if server_arg == "both":
        results.append(run_generation("docker", "jira", model_name))
        results.append(run_generation("docker", "github", model_name))
    else:
        results.append(run_generation("docker", server_arg, model_name))

    # CI/CD (shared)
    results.append(run_generation("ci", "both", model_name))

    return results

# Comparison results file

COMPARISON_CSV = Path("evaluation/model_comparison.csv")
COMPARISON_HEADERS = [
    "run_id", "timestamp", "model", "model_display", "server",
    "artefact", "duration_secs", "tokens_total", "cost_usd",
    "parse_success", "validation_errors_count", "generation_success",
]


def ensure_comparison_csv():
    COMPARISON_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not COMPARISON_CSV.exists() or COMPARISON_CSV.stat().st_size == 0:
        import csv
        with open(COMPARISON_CSV, "w", newline="") as f:
            csv.writer(f).writerow(COMPARISON_HEADERS)


def append_comparison_row(result: dict):
    import csv
    ensure_comparison_csv()
    row = {
        "run_id": result.get("run_id", ""),
        "timestamp": result.get("timestamp", ""),
        "model": result.get("model", ""),
        "model_display": result.get("model_display", ""),
        "server": result.get("server", ""),
        "artefact": result.get("artefact", ""),
        "duration_secs": result.get("duration_secs", 0),
        "tokens_total": result.get("tokens_total", 0),
        "cost_usd": result.get("cost_usd", 0),
        "parse_success": 1 if result.get("parse_success") else 0,
        "validation_errors_count": len(result.get("validation_errors", [])),
        "generation_success": 1 if result.get("success") else 0,
    }
    with open(COMPARISON_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=COMPARISON_HEADERS).writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Multi-LLM artefact generation")
    parser.add_argument("--model", choices=list(MODELS.keys()) + ["all"], required=True)
    parser.add_argument("--artefact", choices=["terraform", "docker", "ci", "all"], required=True)
    parser.add_argument("--server", choices=["jira", "github", "both"], required=True)
    parser.add_argument("--repeat", type=int, default=1, help="Repeat N times per model")
    args = parser.parse_args()

    if args.model == "all":
        model_list = list(MODELS.keys())
    else:
        model_list = [args.model]

    for model_name in model_list:
        config = MODELS[model_name]
        if not os.getenv(config["env_key"]):
            print(f"ERROR: {config['env_key']} not set for {config['display_name']}")
            sys.exit(1)

    for model_name in model_list:
        provider = MODELS[model_name]["provider"]
        if provider == "openai" and not HAS_OPENAI:
            print("ERROR: pip install openai")
            sys.exit(1)
        if provider == "gemini" and not HAS_GEMINI:
            print("ERROR: pip install google-generativeai")
            sys.exit(1)
        if provider == "anthropic" and not HAS_ANTHROPIC:
            print("ERROR: pip install anthropic")
            sys.exit(1)

    ensure_comparison_csv()

    all_results = []
    for rep in range(1, args.repeat + 1):
        for model_name in model_list:
            config = MODELS[model_name]
            print(f"\n{'='*60}")
            print(f"  MODEL: {config['display_name']} (rep {rep}/{args.repeat})")
            print(f"{'='*60}")

            if args.artefact == "all":
                results = run_full_generation(model_name, args.server)
            else:
                if args.artefact == "docker" and args.server == "both":
                    results = [
                        run_generation(args.artefact, "jira", model_name),
                        run_generation(args.artefact, "github", model_name),
                    ]
                else:
                    server = args.server if args.artefact != "ci" else "both"
                    results = [run_generation(args.artefact, server, model_name)]

            for r in results:
                append_comparison_row(r)
                all_results.append(r)

    print(f"\n{'='*60}")
    print(f"  MULTI-LLM COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Model':<22} {'Runs':>5} {'Success':>8} {'Avg Time':>10} {'Avg Tokens':>11} {'Total Cost':>11}")
    print(f"  {'─'*70}")

    for model_name in model_list:
        config = MODELS[model_name]
        model_results = [r for r in all_results if r.get("model") == model_name]
        n = len(model_results)
        successes = sum(1 for r in model_results if r.get("success"))
        avg_time = sum(r.get("duration_secs", 0) for r in model_results) / max(n, 1)
        avg_tokens = sum(r.get("tokens_total", 0) for r in model_results) / max(n, 1)
        total_cost = sum(r.get("cost_usd", 0) for r in model_results)

        print(f"  {config['display_name']:<22} {n:>5} {successes:>5}/{n:<2} {avg_time:>9.1f}s {avg_tokens:>10.0f} ${total_cost:>9.4f}")

    print(f"\n  Results saved to: {COMPARISON_CSV}")
    print(f"  Generate charts with: python evaluation/plot_comparison.py")


if __name__ == "__main__":
    main()
