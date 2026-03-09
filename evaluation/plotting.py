#!/usr/bin/env python3
"""
 Generate thesis-ready charts from experiment results

Produces boxplots, bar charts, and comparison plots using matplotlib only.

Usage:
    python plotting.py                           # Default: read evaluation/results.csv
    python plotting.py --csv results.csv --output evaluation/report/

"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
except ImportError:
    print("ERROR: matplotlib not installed. Run: pip install matplotlib")
    sys.exit(1)

RESULTS_FILE = Path("evaluation/results.csv")
OUTPUT_DIR = Path("evaluation/report")

# Thesis-appropriate style
COLORS = {"manual": "#2B579A", "llm": "#E87D2F"}
LABELS = {"manual": "Manual Baseline", "llm": "LLM-Assisted"}

def load_data(filepath: Path) -> list[dict]:
    rows = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in row:
                val = row[key].strip()
                if val == "":
                    row[key] = None
                else:
                    try:
                        row[key] = float(val) if "." in val else int(val)
                    except ValueError:
                        row[key] = val
            rows.append(row)
    return rows

def extract(data, server, approach, phase, field):
    return [r[field] for r in data
            if r.get("server") == server
            and r.get("approach") == approach
            and r.get("phase") == phase
            and r.get(field) is not None]

def setup_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
    })

def plot_time_comparison(data, output_dir):
    """Boxplot: deployment time — Manual vs LLM, per server."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 5), sharey=True)

    for idx, server in enumerate(["jira", "github"]):
        ax = axes[idx]
        manual_t = extract(data, server, "manual", "A_initial", "t_total_secs")
        llm_t = extract(data, server, "llm", "A_initial", "t_total_secs")

        if not manual_t and not llm_t:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(f"{server.upper()} — Phase A")
            continue

        bp = ax.boxplot(
            [manual_t, llm_t],
            labels=["Manual", "LLM"],
            patch_artist=True,
            widths=0.5,
            medianprops={"color": "black", "linewidth": 1.5},
        )
        bp["boxes"][0].set_facecolor(COLORS["manual"])
        bp["boxes"][0].set_alpha(0.7)
        if len(bp["boxes"]) > 1:
            bp["boxes"][1].set_facecolor(COLORS["llm"])
            bp["boxes"][1].set_alpha(0.7)

        # Add median labels
        for i, vals in enumerate([manual_t, llm_t]):
            if vals:
                med = sorted(vals)[len(vals) // 2]
                ax.annotate(f"{med:.0f}s", xy=(i + 1, med), ha="center", va="bottom",
                           fontsize=9, fontweight="bold")

        ax.set_title(f"{server.upper()} — Phase A")
        ax.set_ylabel("Deployment Time (seconds)" if idx == 0 else "")
        n_manual = len(manual_t)
        n_llm = len(llm_t)
        ax.set_xlabel(f"N = {n_manual} / {n_llm}")

    fig.suptitle("End-to-End Deployment Time: Manual vs LLM-Assisted", fontsize=14, fontweight="bold")
    plt.tight_layout()
    out = output_dir / "time_comparison.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")

def plot_correctness(data, output_dir):
    """Bar chart: correctness score with error bars."""
    fig, ax = plt.subplots(figsize=(8, 5))

    servers = ["jira", "github"]
    x_positions = [0, 1, 3, 4]  # Gap between servers
    bar_data = []

    for server in servers:
        for approach in ["manual", "llm"]:
            scores = extract(data, server, approach, "A_initial", "correctness_score")
            mean = sum(scores) / len(scores) if scores else 0
            std = (sum((x - mean) ** 2 for x in scores) / max(len(scores) - 1, 1)) ** 0.5 if len(scores) > 1 else 0
            bar_data.append((mean, std, approach, len(scores)))

    bars = ax.bar(
        x_positions,
        [d[0] for d in bar_data],
        yerr=[d[1] for d in bar_data],
        width=0.7,
        color=[COLORS[d[2]] for d in bar_data],
        alpha=0.8,
        capsize=5,
        edgecolor="white",
        linewidth=0.5,
    )

    # Labels on bars
    for bar, d in zip(bars, bar_data):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{d[0]:.2f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, -0.06,
                f"N={d[3]}", ha="center", va="top", fontsize=8, color="gray")

    ax.set_xticks([0.5, 3.5])
    ax.set_xticklabels(["Jira", "GitHub"])
    ax.set_ylabel("Correctness Score")
    ax.set_ylim(0, 1.15)
    ax.set_title("Correctness Score: Manual vs LLM-Assisted", fontweight="bold")

    legend_handles = [mpatches.Patch(color=COLORS["manual"], alpha=0.8, label="Manual"),
                      mpatches.Patch(color=COLORS["llm"], alpha=0.8, label="LLM")]
    ax.legend(handles=legend_handles, loc="upper right")

    plt.tight_layout()
    out = output_dir / "correctness_comparison.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")

def plot_reliability(data, output_dir):
    """Stacked bar: success vs failure counts."""
    fig, ax = plt.subplots(figsize=(8, 5))

    categories = []
    successes = []
    failures = []

    for server in ["jira", "github"]:
        for approach in ["manual", "llm"]:
            success_vals = extract(data, server, approach, "A_initial", "success")
            s = sum(1 for v in success_vals if v == 1)
            f = sum(1 for v in success_vals if v == 0)
            categories.append(f"{server.upper()}\n{LABELS[approach]}")
            successes.append(s)
            failures.append(f)

    x = range(len(categories))
    bars_success = ax.bar(x, successes, color="#27AE60", alpha=0.8, label="Success")
    bars_failure = ax.bar(x, failures, bottom=successes, color="#E74C3C", alpha=0.8, label="Failure")

    # Labels
    for i, (s, f) in enumerate(zip(successes, failures)):
        total = s + f
        if total > 0:
            rate = s / total
            ax.text(i, s + f + 0.3, f"{rate:.0%}", ha="center", fontweight="bold", fontsize=10)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylabel("Number of Runs")
    ax.set_title("Deployment Reliability: Success vs Failure", fontweight="bold")
    ax.legend(loc="upper right")

    plt.tight_layout()
    out = output_dir / "reliability_comparison.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")

def plot_cost(data, output_dir):
    """Bar chart: cost breakdown per approach."""
    fig, ax = plt.subplots(figsize=(8, 5))

    categories = []
    aws_costs = []
    llm_costs = []

    for server in ["jira", "github"]:
        for approach in ["manual", "llm"]:
            rows = [r for r in data
                    if r.get("server") == server
                    and r.get("approach") == approach
                    and r.get("phase") == "A_initial"
                    and r.get("success") == 1]
            if rows:
                aws_c = [r.get("aws_cost_eur", 0) or 0 for r in rows]
                llm_c = [r.get("llm_cost_eur", 0) or 0 for r in rows]
                categories.append(f"{server.upper()}\n{LABELS[approach]}")
                aws_costs.append(sum(aws_c) / len(aws_c))
                llm_costs.append(sum(llm_c) / len(llm_c))

    if not categories:
        print("  Skipped cost chart (no successful runs)")
        return

    x = range(len(categories))
    ax.bar(x, aws_costs, color="#3498DB", alpha=0.8, label="AWS Cost")
    ax.bar(x, llm_costs, bottom=aws_costs, color="#F39C12", alpha=0.8, label="LLM Token Cost")

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylabel("Cost per Successful Deployment (EUR)")
    ax.set_title("Cost Breakdown: AWS + LLM per Deployment", fontweight="bold")
    ax.legend()

    plt.tight_layout()
    out = output_dir / "cost_breakdown.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")

def main():
    setup_style()

    parser = argparse.ArgumentParser(description="Generate thesis charts")
    parser.add_argument("--csv", default=str(RESULTS_FILE))
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    data = load_data(Path(args.csv))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loaded {len(data)} rows from {args.csv}")
    print(f"Generating charts to {output_dir}/\n")

    plot_time_comparison(data, output_dir)
    plot_correctness(data, output_dir)
    plot_reliability(data, output_dir)
    plot_cost(data, output_dir)

    print(f"\nDone. All charts saved to {output_dir}/")

if __name__ == "__main__":
    main()