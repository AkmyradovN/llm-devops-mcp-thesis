## Identity Columns

| Column | Type | How to Fill |
|--------|------|-------------|
| `run_id` | String | Format: `{server}-{approach}-{phase}-{run_number}` e.g. `jira-manual-A-001` |
| `timestamp_start` | ISO datetime | When deployment started, e.g. `2026-03-07T02:12:00Z` |
| `timestamp_end` | ISO datetime | When health check passed (or run was marked failed) |
| `server` | Enum | `jira` or `github` |
| `approach` | Enum | `manual` or `llm` |
| `phase` | Enum | `A_initial` or `B_change` |

## Correctness Columns

| Column | Type | How to Fill |
|--------|------|-------------|
| `syntax_errors_count` | Integer | Run `validate_syntax.sh` on generated files. Count total errors. For manual baseline, run on your own files too (should be 0). |
| `missing_fields_count` | Integer | Compare files against the correctness checklist. Count unchecked items. |
| `wrong_config_count` | Integer | Compare files against `expected_config.json`. Count mismatched values. |
| `manual_edits_lines` | Integer | For manual: always `0`. For LLM: count non-whitespace lines changed to fix LLM output. Use `git diff --stat`. |
| `correctness_score` | Float | Computed: `max(0, 1 - (syntax_errors + missing_fields + wrong_config) / 25)` |
| `health_endpoint_pass` | 0 or 1 | Did `/health` return HTTP 200 with correct JSON? |
| `functional_endpoint_pass` | 0 or 1 | Did `/create_ticket` or `/create_issue` return `"status": "success"`? |

## Efficiency Columns

| Column | Type | How to Fill |
|--------|------|-------------|
| `t_gen_secs` | Float | LLM only: wall-clock seconds for API call(s). `run_llm.py` records this. Manual: `0`. |
| `t_author_secs` | Float | Manual only: seconds you spent writing the files. LLM: `0`. |
| `t_pipeline_secs` | Float | From CI/CD start to health-check pass. Read from GitHub Actions log or `deploy_to_ec2.sh` output. |
| `t_total_secs` | Float | Computed: `t_gen_secs + t_pipeline_secs` (LLM) or `t_author_secs + t_pipeline_secs` (manual). |
| `speedup` | Float | Computed later: `manual_t_total / llm_t_total` for matched pairs. Leave blank during collection. |
| `peak_memory_mb` | Float | From `monitor_resources.sh` on EC2 during deployment. |
| `disk_usage_mb` | Float | From `measure_disk.sh` — Docker image sizes after deployment. |

## Reliability Columns

| Column | Type | How to Fill |
|--------|------|-------------|
| `success` | 0 or 1 | `1` if both health check and functional test pass; `0` otherwise. |
| `attempts` | Integer | `1` if first-try success. `2` or `3` if retries were needed. Max 3. |
| `rollback_triggered` | 0 or 1 | `1` if `terraform destroy` was run to recover from failure. |
| `failure_category` | String | If `success=0`: one of `syntax_error`, `runtime_error`, `timeout`, `network_error`, `resource_limit`, `unknown`. If `success=1`: leave empty. |

## Adaptability Columns (Phase B only)

| Column | Type | How to Fill |
|--------|------|-------------|
| `prompts_to_fix` | Integer | LLM only, Phase B only: number of prompt rounds to produce working adapted config. Manual: leave empty. |
| `edit_span_lines` | Integer | Phase B only: `git diff --stat` line count between Phase A and Phase B versions. |
| `time_to_adapt_secs` | Float | Phase B only: total time from receiving change requirement to successful deployment. |
| `adaptation_success` | 0 or 1 | Phase B only: did the adapted deployment pass all checks? |

## Cost Columns

| Column | Type | How to Fill |
|--------|------|-------------|
| `aws_runtime_mins` | Float | Minutes the EC2 instance ran for this deployment (from start to teardown). |
| `aws_cost_eur` | Float | Computed: `(aws_runtime_mins / 60) * hourly_rate`. t2.micro ~ €0.0116/hr in eu-central-1. |
| `tokens_prompt` | Integer | LLM only: prompt tokens from OpenAI API response. Manual: `0`. |
| `tokens_completion` | Integer | LLM only: completion tokens. Manual: `0`. |
| `tokens_total` | Integer | LLM only: `tokens_prompt + tokens_completion`. Manual: `0`. |
| `llm_cost_eur` | Float | Computed: `(tokens_total / 1000) * price_per_1k`. Manual: `0`. |
| `total_cost_eur` | Float | Computed: `aws_cost_eur + llm_cost_eur`. |

## Notes

| Column | Type | How to Fill |
|--------|------|-------------|
| `notes` | String | Free text. Record anything unusual: errors, workarounds, observations. |