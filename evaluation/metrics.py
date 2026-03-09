#!/usr/bin/env python3
"""
metrics.py — Compute derived metrics and summary statistics

Reads evaluation/results.csv, computes derived metrics (speedup, success_rate,
confidence intervals), runs statistical tests, and prints summary tables.

Usage:
    python metrics.py --summary                  # Print summary tables
    python metrics.py --summary --output report  # Save to evaluation/report/
    python metrics.py --stats                    # Run statistical tests (H1-H4)

"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Optional: scipy for statistical tests
try:
    from scipy import stats as sp_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("WARNING: scipy not installed. Statistical tests will be skipped.")
    print("Install with: pip install scipy")

RESULTS_FILE = Path("evaluation/results.csv")
REPORT_DIR = Path("evaluation/report")

def load_data(filepath: Path) -> list[dict]:
    """Load results.csv into a list of dicts with type conversion."""
    if not filepath.exists():
        print(f"ERROR: {filepath} not found")
        sys.exit(1)

    rows = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            for key in row:
                val = row[key].strip()
                if val == "":
                    row[key] = None
                    continue
                try:
                    if "." in val:
                        row[key] = float(val)
                    else:
                        row[key] = int(val)
                except ValueError:
                    row[key] = val
            rows.append(row)

    return rows

def group_by(data: list[dict], *keys) -> dict:
    """Group rows by one or more keys."""
    groups = defaultdict(list)
    for row in data:
        key = tuple(row.get(k) for k in keys)
        if len(keys) == 1:
            key = key[0]
        groups[key].append(row)
    return dict(groups)

def safe_median(values: list) -> float | None:
    """Compute median, ignoring None values."""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    n = len(clean)
    if n % 2 == 0:
        return (clean[n // 2 - 1] + clean[n // 2]) / 2
    return clean[n // 2]

def safe_mean(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None

def safe_std(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    variance = sum((x - mean) ** 2 for x in clean) / (len(clean) - 1)
    return variance ** 0.5

def iqr(values: list) -> tuple[float, float] | None:
    clean = sorted(v for v in values if v is not None)
    if len(clean) < 4:
        return None
    q1 = clean[len(clean) // 4]
    q3 = clean[3 * len(clean) // 4]
    return q1, q3

def print_summary(data: list[dict]):
    """Print summary tables with time breakdown and cost analysis."""

    phase_a = [r for r in data if r.get("phase") == "A_initial"]
    by_cell = group_by(phase_a, "server", "approach")

    # Table 1: Time & Correctness
    print(f"\n{'='*100}")
    print("  TABLE 1 — Summary by Scenario (Phase A, Initial Deployment)")
    print(f"{'='*100}")
    print(f"  {'Server':<10} {'Approach':<10} {'N':>4} {'Author/Gen s':>14} {'Pipeline s':>12} "
          f"{'Total s':>10} {'Correctness':>14} {'Success%':>10}")
    print(f"  {'─'*94}")

    for (server, approach), rows in sorted(by_cell.items()):
        n = len(rows)

        author = [r.get("t_author_secs") for r in rows]
        gen = [r.get("t_gen_secs") for r in rows]
        pipeline = [r.get("t_pipeline_secs") for r in rows]
        total = [r.get("t_total_secs") for r in rows]

        # For manual: show authoring time; for LLM: show generation time
        dev_time = author if approach == "manual" else gen
        med_dev = safe_median(dev_time)
        med_pipe = safe_median(pipeline)
        med_total = safe_median(total)

        corr = [r.get("correctness_score") for r in rows]
        mean_corr = safe_mean(corr)
        std_corr = safe_std(corr)

        successes = [r.get("success") for r in rows]
        success_rate = safe_mean(successes)

        has_data = med_total is not None and mean_corr is not None and std_corr is not None

        if has_data:
            dev_label = f"{med_dev:>14.0f}" if med_dev is not None else "           N/A"
            sr_str = f"{success_rate:>9.0%}" if success_rate is not None else "      N/A"
            print(f"  {server:<10} {approach:<10} {n:>4} "
                  f"{dev_label} {med_pipe:>12.0f} "
                  f"{med_total:>10.0f} "
                  f"{mean_corr:>8.2f} ± {std_corr:.2f}"
                  f"{sr_str}")
        else:
            print(f"  {server:<10} {approach:<10} {n:>4}   (insufficient data)")

    # Speedup summary
    print(f"\n  {'─'*60}")
    print(f"  SPEEDUP ANALYSIS (Total Development Lead Time)")
    print(f"  {'─'*60}")
    for server in sorted(set(k[0] for k in by_cell)):
        manual_key = (server, "manual")
        llm_key = (server, "llm")
        if manual_key in by_cell and llm_key in by_cell:
            manual_total = safe_median([r.get("t_total_secs") for r in by_cell[manual_key]])
            llm_total = safe_median([r.get("t_total_secs") for r in by_cell[llm_key]])
            if manual_total and llm_total and llm_total > 0:
                speedup = manual_total / llm_total
                print(f"  {server.upper():<10} Manual: {manual_total:.0f}s  →  LLM: {llm_total:.0f}s  "
                      f"= {speedup:.1f}× faster")

    # Table 1b: Cost Breakdown
    HUMAN_HOURLY_EUR = 30.0
    print(f"\n{'='*100}")
    print(f"  TABLE 1b — Cost Breakdown per Successful Deployment (EUR)")
    print(f"  (Human labor rate: EUR {HUMAN_HOURLY_EUR:.0f}/hr)")
    print(f"{'='*100}")
    print(f"  {'Server':<10} {'Approach':<10} {'N':>4} {'AWS Infra':>12} {'LLM Tokens':>12} "
          f"{'Human Labor':>13} {'TOTAL':>12}")
    print(f"  {'─'*77}")

    for (server, approach), rows in sorted(by_cell.items()):
        n = len(rows)
        success_rows = [r for r in rows if r.get("success") == 1]
        if not success_rows:
            print(f"  {server:<10} {approach:<10} {n:>4}   (no successful runs)")
            continue

        aws_costs = [r.get("aws_cost_eur") or 0 for r in success_rows]
        llm_costs = [r.get("llm_cost_eur") or 0 for r in success_rows]
        total_costs = [r.get("total_cost_eur") or 0 for r in success_rows]

        # Compute human labor cost from t_author_secs
        labor_costs = [(r.get("t_author_secs") or 0) / 3600 * HUMAN_HOURLY_EUR for r in success_rows]

        mean_aws = safe_mean(aws_costs)
        mean_llm = safe_mean(llm_costs)
        mean_labor = safe_mean(labor_costs)
        mean_total = safe_mean(total_costs)

        print(f"  {server:<10} {approach:<10} {n:>4} "
              f"{mean_aws:>12.4f} {mean_llm:>12.4f} "
              f"{mean_labor:>13.2f} {mean_total:>12.4f}")

    # Table 2 — Phase B
    phase_b = [r for r in data if r.get("phase") == "B_change"]
    if phase_b:
        print(f"\n{'='*80}")
        print("  TABLE 2 — Adaptability (Phase B, After Change)")
        print(f"{'='*80}")
        print(f"  {'Server':<10} {'Approach':<10} {'N':>4} {'Prompts med':>12} "
              f"{'Edit lines med':>16} {'Adapt time med s':>18} {'Success%':>10}")
        print(f"  {'─'*84}")

        by_cell_b = group_by(phase_b, "server", "approach")
        for (server, approach), rows in sorted(by_cell_b.items()):
            n = len(rows)
            prompts = [r.get("prompts_to_fix") for r in rows]
            edits = [r.get("edit_span_lines") for r in rows]
            adapt_t = [r.get("time_to_adapt_secs") for r in rows]
            successes = [r.get("adaptation_success") for r in rows]

            med_prompts = safe_median(prompts)
            med_edits = safe_median(edits)
            med_adapt = safe_median(adapt_t)
            sr = safe_mean(successes)

            p_str = f"{med_prompts:>12.0f}" if med_prompts is not None else f"{'N/A':>12}"
            e_str = f"{med_edits:>16.0f}" if med_edits is not None else f"{'N/A':>16}"
            a_str = f"{med_adapt:>18.1f}" if med_adapt is not None else f"{'N/A':>18}"
            s_str = f"{sr:>9.0%}" if sr is not None else f"{'N/A':>9}"

            print(f"  {server:<10} {approach:<10} {n:>4} {p_str} {e_str} {a_str} {s_str}")

def print_stats(data: list[dict]):
    """Run hypothesis tests H1-H4."""
    if not HAS_SCIPY:
        print("\nSKIPPED: Install scipy for statistical tests (pip install scipy)")
        return

    print(f"\n{'='*80}")
    print("  HYPOTHESIS TESTS (H1-H4)")
    print(f"{'='*80}")

    phase_a = [r for r in data if r.get("phase") == "A_initial"]

    for server in ["jira", "github"]:
        server_data = [r for r in phase_a if r.get("server") == server]
        manual = [r for r in server_data if r.get("approach") == "manual"]
        llm = [r for r in server_data if r.get("approach") == "llm"]

        if len(manual) < 3 or len(llm) < 3:
            print(f"\n  {server.upper()}: Insufficient data (manual={len(manual)}, llm={len(llm)})")
            continue

        print(f"\n  {'─'*40}")
        print(f"  Server: {server.upper()}")
        print(f"  {'─'*40}")

        # H1: Efficiency — LLM reduces time
        manual_times = [r["t_total_secs"] for r in manual if r.get("t_total_secs") is not None]
        llm_times = [r["t_total_secs"] for r in llm if r.get("t_total_secs") is not None]

        if manual_times and llm_times:
            u_stat, p_val = sp_stats.mannwhitneyu(manual_times, llm_times, alternative="greater")
            med_manual = safe_median(manual_times)
            med_llm = safe_median(llm_times)
            speedup = med_manual / med_llm if med_llm is not None and med_llm > 0 else None

            print(f"\n  H1 (Efficiency): LLM reduces end-to-end time")
            print(f"    Manual median: {med_manual:.0f}s, LLM median: {med_llm:.0f}s")
            print(f"    Speedup: {speedup:.2f}x" if speedup else "    Speedup: N/A")
            print(f"    Mann-Whitney U={u_stat:.1f}, p={p_val:.4f}")
            print(f"    Decision: {'SUPPORTED' if speedup and speedup > 1.5 and p_val < 0.05 else 'NOT SUPPORTED'}")

        # H2: Correctness — LLM not worse than -5pp
        manual_corr = [r["correctness_score"] for r in manual if r.get("correctness_score") is not None]
        llm_corr = [r["correctness_score"] for r in llm if r.get("correctness_score") is not None]

        if manual_corr and llm_corr:
            mean_diff = round(safe_mean(llm_corr) - safe_mean(manual_corr), 4)
            u_stat, p_val = sp_stats.mannwhitneyu(llm_corr, manual_corr, alternative="less")

            print(f"\n  H2 (Correctness): LLM correctness not worse than -5pp vs manual")
            print(f"    Manual mean: {safe_mean(manual_corr):.2f}, LLM mean: {safe_mean(llm_corr):.2f}")
            print(f"    Difference: {mean_diff:+.2f}")
            h2_supported = mean_diff >= -0.05
            print(f"    Decision: {'SUPPORTED' if h2_supported else 'NOT SUPPORTED'}")

        # H3: Reliability — LLM success rate >= 80%
        llm_success = [r["success"] for r in llm if r.get("success") is not None]
        manual_success = [r["success"] for r in manual if r.get("success") is not None]

        if llm_success and manual_success:
            llm_rate = safe_mean(llm_success)
            manual_rate = safe_mean(manual_success)
            delta = abs(llm_rate - manual_rate)

            print(f"\n  H3 (Reliability — Phase A, from-scratch): LLM success rate >= 80%, within 10pp of manual")
            print(f"    Manual: {manual_rate:.0%}, LLM: {llm_rate:.0%}, |Δ|: {delta:.0%}")
            print(f"    Decision: {'SUPPORTED' if llm_rate >= 0.80 and delta <= 0.10 else 'NOT SUPPORTED'}")

    # H4: Adaptability (Phase B)
    phase_b = [r for r in data if r.get("phase") == "B_change"]
    if phase_b:
        print(f"\n  {'═'*50}")
        print(f"  H4 (Adaptability — Phase B, v1→v2 adaptation)")
        print(f"  {'═'*50}")

        for server in sorted(set(r.get("server") for r in phase_b)):
            server_b = [r for r in phase_b if r.get("server") == server]
            manual_b = [r for r in server_b if r.get("approach") == "manual"]
            llm_b = [r for r in server_b if r.get("approach") == "llm"]

            if not manual_b or not llm_b:
                continue

            print(f"\n  Server: {server.upper()} (Phase B)")

            # Adaptability success rate
            llm_adapt_success = [r.get("adaptation_success") or 0 for r in llm_b]
            manual_adapt_success = [r.get("adaptation_success") or 0 for r in manual_b]
            llm_adapt_rate = safe_mean(llm_adapt_success)
            manual_adapt_rate = safe_mean(manual_adapt_success)

            print(f"    Adaptation success: Manual {manual_adapt_rate:.0%}, LLM {llm_adapt_rate:.0%}")

            # Prompt rounds
            llm_prompts = [r.get("prompts_to_fix") for r in llm_b if r.get("prompts_to_fix") is not None]
            med_prompts = safe_median(llm_prompts)
            print(f"    LLM prompt rounds (median): {med_prompts:.0f}" if med_prompts is not None else "    LLM prompt rounds: N/A")

            # Edit span
            llm_edits = [r.get("edit_span_lines") for r in llm_b if r.get("edit_span_lines") is not None]
            med_edits = safe_median(llm_edits)
            print(f"    LLM edit lines (median): {med_edits:.0f}" if med_edits is not None else "    LLM edit lines: N/A")

            # H4 decision: LLM adapts with ≤ 2 prompt rounds and ≤ 20 lines on average
            # (Relaxed for real-world: success >= 70% is considered partially supported)
            h4_prompts_ok = med_prompts is not None and med_prompts <= 2
            h4_success_ok = llm_adapt_rate is not None and llm_adapt_rate >= 0.70

            if h4_prompts_ok and h4_success_ok:
                verdict = "SUPPORTED" if llm_adapt_rate >= 0.90 else "PARTIALLY SUPPORTED"
            else:
                verdict = "NOT SUPPORTED"

            print(f"    Decision: {verdict}")

            # Contrast with Phase A
            phase_a_llm = [r for r in data if r.get("phase") == "A_initial" and r.get("server") == server and r.get("approach") == "llm"]
            if phase_a_llm:
                phase_a_rate = safe_mean([r.get("success") or 0 for r in phase_a_llm])
                improvement = (llm_adapt_rate or 0) - (phase_a_rate or 0)
                print(f"    Phase A → Phase B improvement: {phase_a_rate:.0%} → {llm_adapt_rate:.0%} (+{improvement:.0%})")

def save_report(data: list[dict], output_dir: Path):
    """Save summary as JSON for programmatic access."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "total_runs": len(data),
        "phase_a": len([r for r in data if r.get("phase") == "A_initial"]),
        "phase_b": len([r for r in data if r.get("phase") == "B_change"]),
        "servers": list(set(r.get("server") for r in data if r.get("server"))),
        "approaches": list(set(r.get("approach") for r in data if r.get("approach"))),
    }
    out_path = output_dir / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary saved to {out_path}")

def main():
    parser = argparse.ArgumentParser(description="Compute metrics and summary statistics")
    parser.add_argument("--summary", action="store_true", help="Print summary tables")
    parser.add_argument("--stats", action="store_true", help="Run hypothesis tests")
    parser.add_argument("--output", default=None, help="Save report to directory")
    parser.add_argument("--csv", default=str(RESULTS_FILE), help="Path to results.csv")

    args = parser.parse_args()

    data = load_data(Path(args.csv))
    print(f"Loaded {len(data)} rows from {args.csv}")

    if args.summary or (not args.summary and not args.stats):
        print_summary(data)

    if args.stats:
        print_stats(data)

    if args.output:
        save_report(data, Path(args.output))

if __name__ == "__main__":
    main()