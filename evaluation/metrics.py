#!/usr/bin/env python3
"""
metrics.py — Compute derived metrics and summary statistics
=============================================================================
Reads evaluation/results.csv, computes derived metrics (speedup, success_rate,
confidence intervals), runs statistical tests, and prints summary tables.

Usage:
    python metrics.py --summary                  # Print summary tables
    python metrics.py --summary --output report  # Save to evaluation/report/
    python metrics.py --stats                    # Run statistical tests (H1-H4)
=============================================================================
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
    """Print Table 1 and Table 2 from the Research Plan."""
    print(f"\n{'='*80}")
    print("  TABLE 1 — Summary by Scenario (Phase A, Initial Deployment)")
    print(f"{'='*80}")
    print(f"  {'Server':<10} {'Approach':<10} {'N':>4} {'Time med(IQR) s':>20} "
          f"{'Correctness':>14} {'Success%':>10} {'Cost/Success €':>16}")
    print(f"  {'─'*84}")

    phase_a = [r for r in data if r.get("phase") == "A_initial"]
    by_cell = group_by(phase_a, "server", "approach")

    for (server, approach), rows in sorted(by_cell.items()):
        n = len(rows)
        times = [r.get("t_total_secs") for r in rows]
        med_time = safe_median(times)
        iqr_vals = iqr(times)
        iqr_str = f"({iqr_vals[0]:.0f}-{iqr_vals[1]:.0f})" if iqr_vals else "(N/A)"

        corr = [r.get("correctness_score") for r in rows]
        mean_corr = safe_mean(corr)
        std_corr = safe_std(corr)

        successes = [r.get("success") for r in rows]
        success_rate = safe_mean(successes)

        costs = [r.get("total_cost_eur") for r in rows if r.get("success") == 1]
        mean_cost = safe_mean(costs)

        print(f"  {server:<10} {approach:<10} {n:>4} "
              f"{med_time:>8.0f} {iqr_str:>11} "
              f"{mean_corr:>8.2f} ± {std_corr:.2f}" if mean_corr and std_corr else "",
              end="")
        if mean_corr and std_corr:
            print(f" {success_rate:>9.0%}" if success_rate is not None else "       N/A", end="")
            print(f" {mean_cost:>15.4f}" if mean_cost else "            N/A")
        else:
            print(f"  (insufficient data)")

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

            print(f"  {server:<10} {approach:<10} {n:>4} "
                  f"{safe_median(prompts) or 'N/A':>12} "
                  f"{safe_median(edits) or 'N/A':>16} "
                  f"{safe_median(adapt_t) or 'N/A':>18} "
                  f"{safe_mean(successes):>9.0%}" if safe_mean(successes) is not None else "")


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
            speedup = med_manual / med_llm if med_llm and med_llm > 0 else None

            print(f"\n  H1 (Efficiency): LLM reduces end-to-end time")
            print(f"    Manual median: {med_manual:.0f}s, LLM median: {med_llm:.0f}s")
            print(f"    Speedup: {speedup:.2f}x" if speedup else "    Speedup: N/A")
            print(f"    Mann-Whitney U={u_stat:.1f}, p={p_val:.4f}")
            print(f"    Decision: {'SUPPORTED' if speedup and speedup > 1.5 and p_val < 0.05 else 'NOT SUPPORTED'}")

        # H2: Correctness — LLM not worse than -5pp
        manual_corr = [r["correctness_score"] for r in manual if r.get("correctness_score") is not None]
        llm_corr = [r["correctness_score"] for r in llm if r.get("correctness_score") is not None]

        if manual_corr and llm_corr:
            mean_diff = safe_mean(llm_corr) - safe_mean(manual_corr)
            u_stat, p_val = sp_stats.mannwhitneyu(llm_corr, manual_corr, alternative="less")

            print(f"\n  H2 (Correctness): LLM correctness not worse than -5pp vs manual")
            print(f"    Manual mean: {safe_mean(manual_corr):.2f}, LLM mean: {safe_mean(llm_corr):.2f}")
            print(f"    Difference: {mean_diff:+.2f}")
            print(f"    Decision: {'SUPPORTED' if mean_diff >= -0.05 else 'NOT SUPPORTED'}")

        # H3: Reliability — LLM success rate >= 80%
        llm_success = [r["success"] for r in llm if r.get("success") is not None]
        manual_success = [r["success"] for r in manual if r.get("success") is not None]

        if llm_success and manual_success:
            llm_rate = safe_mean(llm_success)
            manual_rate = safe_mean(manual_success)
            delta = abs(llm_rate - manual_rate)

            print(f"\n  H3 (Reliability): LLM success rate >= 80%, within 10pp of manual")
            print(f"    Manual: {manual_rate:.0%}, LLM: {llm_rate:.0%}, |Δ|: {delta:.0%}")
            print(f"    Decision: {'SUPPORTED' if llm_rate >= 0.80 and delta <= 0.10 else 'NOT SUPPORTED'}")


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