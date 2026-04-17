# LLM-Assisted DevOps with MCP — Thesis Evaluation

This repository contains all source code, evaluation scripts, and results for the thesis:

> **"Evaluating LLM-Assisted DevOps Automation Using the Model Context Protocol (MCP)"**

A reviewer, committee member, or future researcher should be able to clone this repository, install the dependencies, and reproduce all experimental results by following the steps below. No GUI is required — all scripts run from the terminal.

---

## Repository Structure

```
.
├── README.md                        ← You are here
├── requirements.txt                 ← All Python dependencies
├── run_llm_multi.py                 ← Multi-LLM comparison script (Phase C)
├── docker_cleanup.sh                ← Helper to clean Docker containers on EC2
│
├── llm-assisted/                    ← LLM-assisted pipeline (Phase A, B)
│   ├── run_llm.py                   ← Single-model artefact generator (GPT-3.5 Turbo)
│   ├── prompts/                     ← Prompt templates for terraform / docker / ci
│   └── schemas/                     ← JSON schemas for output validation
│
├── manual-baseline/                 ← Hand-written DevOps artefacts
│   ├── docker/github/               ← GitHub MCP server (Dockerfile, app.py, requirements.txt)
│   ├── docker/jira/                 ← Jira MCP server (Dockerfile, app.py, requirements.txt)
│   ├── .github/workflows/deploy.yml ← CI/CD workflow (manual)
│   └── terraform/                   ← Terraform infrastructure (main.tf, outputs.tf, variables.tf)
│
├── evaluation/
│   ├── results.csv                  ← Phase A & B experiment results (Phases A+B tables)
│   ├── model_comparison.csv         ← Multi-LLM generation results (Phase C table)
│   ├── results_column_guide.md      ← Column definitions for results.csv
│   ├── run_experiment.py            ← Phase A/B experiment orchestrator (requires EC2)
│   ├── metrics.py                   ← Computes summary statistics and hypothesis tests
│   ├── plotting.py                  ← Generates Phase A/B thesis charts
│   ├── plot_comparison.py           ← Generates Phase C multi-LLM charts
│   ├── scripts/
│   │   ├── check_completeness.py    ← Static correctness checker
│   │   ├── test_endpoints.py        ← Live endpoint functional tests
│   │   ├── validate_syntax.sh       ← Bash: YAML/Terraform syntax validation
│   │   └── verify_health.sh         ← Bash: health endpoint check via curl
│   └── report/                      ← Generated PNG charts (committed for reference)
│
├── docs/
│   ├── correctness_checklist_github.md
│   ├── correctness_checklist_jira.md
│   └── expected_config.json         ← Reference configuration for completeness checks
│
└── logs/                            ← Generated run logs (created at runtime)
```

---

## 1. Prerequisites

- Python **3.10 or higher**
- `git`
- Internet access (for LLM API calls)
- For **Phase A/B only**: an AWS EC2 instance (t2.micro) with SSH access and a `.pem` key

---

## 2. Installation

```bash
# 1. Clone the repository
git clone https://github.com/AkmyradovN/llm-devops-mcp-thesis.git
cd llm-devops-mcp-thesis

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate.bat    # Windows

# 3. Install all dependencies
pip install -r requirements.txt
```

---

## 3. API Key Setup

The scripts need API keys for the LLM providers used in the experiments. Set the relevant keys as environment variables **before** running any script.

```bash
# Required for Phase A / B (GPT-3.5 Turbo, run_experiment.py + run_llm.py)
export OPENAI_API_KEY="sk-..."

# Required for Phase C multi-LLM comparison (run_llm_multi.py)
export OPENAI_API_KEY="sk-..."           # GPT-3.5 Turbo
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude Sonnet 4.5
export GOOGLE_API_KEY="AIza..."         # Gemini 2.5 Flash
```

> **Note:** You only need to set the keys for the models you want to run.
> The scripts will print a clear error and exit if a required key is missing.

---

## 4. Reproducing Results — Script Guide

### 4.1 Phase C — Multi-LLM Comparison (Recommended starting point)

This is the simplest experiment to reproduce. It runs all three LLMs against the same four generation tasks and records results to `evaluation/model_comparison.csv`.

**The data supporting the thesis tables in Section 5.3 comes from this script.**

```bash
# Run all three models, all artefact types, 5 times each (matching the thesis setup)
python run_llm_multi.py --model all --artefact all --server both --repeat 5

# Or run a single model to test:
python run_llm_multi.py --model claude-sonnet-4-5 --artefact all --server both --repeat 1
python run_llm_multi.py --model gemini-2.5-flash  --artefact all --server both --repeat 1
python run_llm_multi.py --model gpt-3.5-turbo     --artefact all --server both --repeat 1
```

Available options:
| Flag | Values | Description |
|------|--------|-------------|
| `--model` | `gpt-3.5-turbo`, `gemini-2.5-flash`, `claude-sonnet-4-5`, `all` | Which model(s) to use |
| `--artefact` | `terraform`, `docker`, `ci`, `all` | Which artefact type to generate |
| `--server` | `jira`, `github`, `both` | Target MCP server |
| `--repeat` | integer (default: 1) | Number of repetitions per model |

Results are appended to `evaluation/model_comparison.csv`.

---

### 4.2 Generate Phase C Charts

After running `run_llm_multi.py` (or using the committed `model_comparison.csv`):

```bash
python evaluation/plot_comparison.py
```

This reads `evaluation/model_comparison.csv` and saves five PNG charts to `evaluation/report/`:

| Chart file | What it shows |
|---|---|
| `multi_llm_generation_time.png` | Generation latency boxplot per model |
| `multi_llm_success_rate.png` | Success rate by model and artefact type |
| `multi_llm_token_usage.png` | Average token consumption per model |
| `multi_llm_cost.png` | Total API cost per model |
| `multi_llm_combined_summary.png` | Combined 2×2 summary panel |

The script also prints a summary table to the terminal.

---

### 4.3 Phase A / B — Deployment Experiment (Requires EC2)

> **Note:** This experiment requires a live AWS EC2 instance.  
> The results are already committed in `evaluation/results.csv` for reviewers who do not have EC2 access.

If you have an EC2 instance:

```bash
# Set connection details
export EC2_IP="your.ec2.ip.address"
export PEM_PATH="/path/to/your-key.pem"

# Run all Phase A combinations (jira + github × manual + llm), 5 repetitions each
python evaluation/run_experiment.py --all-phase-a --repeat 5

# Or run a single combination:
python evaluation/run_experiment.py --server jira --approach llm --phase A_initial
python evaluation/run_experiment.py --server jira --approach manual --phase A_initial

# Phase B (post-change adaptation):
python evaluation/run_experiment.py --server jira --approach llm --phase B_change
python evaluation/run_experiment.py --server jira --approach manual --phase B_change
```

Results are appended to `evaluation/results.csv`. The script:
1. Generates artefacts (LLM approach) or uses hand-written files (manual approach)
2. Deploys Docker containers to EC2 via SSH/SCP
3. Runs health endpoint checks (`/health`)
4. Runs functional endpoint tests (`/create_ticket`, `/create_issue`, etc.)
5. Runs completeness checks against the reference configuration
6. Writes a row to `evaluation/results.csv`

---

### 4.4 Compute Phase A/B Statistics and Charts

```bash
# Print summary statistics (correctness, time, cost per approach/phase)
python evaluation/metrics.py --summary

# Run statistical tests (Mann-Whitney U, effect sizes) for hypotheses H1–H4
python evaluation/metrics.py --stats

# Generate Phase A/B charts (reads evaluation/results.csv)
python evaluation/plotting.py
```

Charts are saved to `evaluation/report/`.

---

### 4.5 Static Validation Scripts (no EC2 needed)

These can be run against the committed `manual-baseline/` files:

```bash
# Check Terraform syntax (requires terraform CLI)
bash evaluation/scripts/validate_syntax.sh manual-baseline/terraform/

# Check YAML syntax (requires yamllint)
bash evaluation/scripts/validate_syntax.sh manual-baseline/.github/workflows/deploy.yml

# Run completeness check against manual-baseline files
python evaluation/scripts/check_completeness.py \
  --server jira \
  --tf-dir manual-baseline/terraform \
  --docker-dir manual-baseline/docker/jira \
  --ci-yaml "manual-baseline/.github/workflows/deploy.yml" \
  --branch manual-baseline

# Run live endpoint tests (requires running containers)
# export EC2_IP=...
python evaluation/scripts/test_endpoints.py
```

---

## 5. Results Summary (committed data)

The thesis results are reproducible from the committed CSV files without re-running any experiments:

| File | Contains | Thesis chapter |
|---|---|---|
| `evaluation/results.csv` | Phase A & B deployment experiments (manual vs LLM) | Chapter 5 — Sections 5.1, 5.2 |
| `evaluation/model_comparison.csv` | Phase C multi-LLM generation comparison | Chapter 5 — Section 5.3 |
| `evaluation/report/*.png` | All thesis figures | Chapter 5 |

To regenerate all charts from the committed data:

```bash
python evaluation/plotting.py       # Phase A/B charts
python evaluation/plot_comparison.py  # Phase C charts
```

---

## 6. Branch Structure

This repository uses three branches, each with a specific role:

| Branch | Purpose |
|---|---|
| `main` | All runnable scripts, evaluation data, and results — **start here** |
| `llm-assisted` | Development history of the LLM-assisted pipeline; LLM-generated artefact snapshots |
| `manual-baseline` | Development history of the hand-written baseline artefacts |

All files needed to reproduce the results are on `main`.

---

## 7. Troubleshooting

**`ModuleNotFoundError: No module named 'anthropic'`**
→ Run `pip install -r requirements.txt` inside the activated virtual environment.

**`ERROR: ANTHROPIC_API_KEY not set`**
→ Export the key: `export ANTHROPIC_API_KEY="sk-ant-..."`

**`ERROR: EC2_IP not set`**
→ For Phase A/B: set `export EC2_IP=...` and `export PEM_PATH=...`. For chart regeneration only, EC2 is not needed.

**`FileNotFoundError: evaluation/model_comparison.csv`**
→ Run `python run_llm_multi.py --model gpt-3.5-turbo --artefact all --server both` first, or use the committed file already in the repo.

**Gemini 2.5 Flash — low success rate on Docker artefacts**
→ This is a known finding documented in the thesis (Section 5.3). The model generates valid output but the `response_mime_type="application/json"` setting occasionally produces schema-incompatible responses for complex Docker prompts. This is an integration sensitivity, not a model capability failure.
