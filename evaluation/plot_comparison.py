#!/usr/bin/env python3

import argparse
import csv
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
except ImportError:
    print("ERROR: pip install matplotlib numpy")
    exit(1)

COMPARISON_CSV = Path("evaluation/model_comparison.csv")
OUTPUT_DIR = Path("evaluation/report")

# Consistent colours per model
COLORS = { 
    "gpt-3.5-turbo": "#10A37F",       # OpenAI green
    "gemini-2.5-flash": "#4285F4",     # Google blue
    "claude-sonnet-4-5": "#FF9900",   # Anthropic amber
}

DISPLAY_NAMES = {
    "gpt-3.5-turbo": "GPT-3.5 Turbo",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
}


def load_data(filepath):
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


def setup_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
    })


def plot_generation_time(data, output_dir):
    """Boxplot: generation time per model."""
    fig, ax = plt.subplots(figsize=(10, 6))

    models = sorted(set(r["model"] for r in data if r.get("model")))
    positions = range(len(models))
    box_data = []

    for model in models:
        times = [r["duration_secs"] for r in data if r.get("model") == model and r.get("duration_secs") is not None]
        box_data.append(times)

    bp = ax.boxplot(
        box_data,
        labels=[DISPLAY_NAMES.get(m, m) for m in models],
        patch_artist=True,
        widths=0.5,
        medianprops={"color": "black", "linewidth": 2},
    )

    for i, model in enumerate(models):
        bp["boxes"][i].set_facecolor(COLORS.get(model, "#888888"))
        bp["boxes"][i].set_alpha(0.7)
        # Add median label
        if box_data[i]:
            med = sorted(box_data[i])[len(box_data[i]) // 2]
            ax.annotate(f"{med:.1f}s", xy=(i + 1, med), ha="center", va="bottom",
                       fontsize=10, fontweight="bold")

    ax.set_ylabel("Generation Time (seconds)")
    ax.set_title("LLM Generation Time Comparison", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    for i, model in enumerate(models):
        ax.text(i + 1, ax.get_ylim()[0] - 0.5, f"N={len(box_data[i])}", ha="center", fontsize=9, color="gray")

    plt.tight_layout()
    out = output_dir / "multi_llm_generation_time.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_success_rate(data, output_dir):
    """Bar chart: generation success rate per model and artefact type."""
    fig, ax = plt.subplots(figsize=(12, 6))

    models = sorted(set(r["model"] for r in data if r.get("model")))
    artefacts = ["terraform", "docker", "ci"]

    bar_width = 0.22
    x = np.arange(len(artefacts))

    for i, model in enumerate(models):
        rates = []
        counts = []
        for art in artefacts:
            runs = [r for r in data if r.get("model") == model and r.get("artefact") == art]
            if runs:
                success = sum(1 for r in runs if r.get("generation_success") == 1)
                rates.append(success / len(runs) * 100)
                counts.append(len(runs))
            else:
                rates.append(0)
                counts.append(0)

        bars = ax.bar(x + i * bar_width, rates, bar_width,
                     label=DISPLAY_NAMES.get(model, model),
                     color=COLORS.get(model, "#888888"), alpha=0.8, edgecolor="white")

        # Add value labels
        for bar, rate, count in zip(bars, rates, counts):
            if count > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                       f"{rate:.0f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.set_xticks(x + bar_width)
    ax.set_xticklabels(["Terraform", "Dockerfile + App", "CI/CD Workflow"])
    ax.set_ylabel("Generation Success Rate (%)")
    ax.set_ylim(0, 115)
    ax.set_title("LLM Generation Success Rate by Artefact Type", fontweight="bold")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out = output_dir / "multi_llm_success_rate.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_token_usage(data, output_dir):
    """Bar chart: average token usage per model."""
    fig, ax = plt.subplots(figsize=(10, 6))

    models = sorted(set(r["model"] for r in data if r.get("model")))
    avg_tokens = []

    for model in models:
        tokens = [r["tokens_total"] for r in data if r.get("model") == model and r.get("tokens_total") is not None]
        avg = sum(tokens) / len(tokens) if tokens else 0
        avg_tokens.append(avg)

    bars = ax.bar(
        [DISPLAY_NAMES.get(m, m) for m in models],
        avg_tokens,
        color=[COLORS.get(m, "#888888") for m in models],
        alpha=0.8, edgecolor="white", width=0.5,
    )

    for bar, val in zip(bars, avg_tokens):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 50,
               f"{val:.0f}", ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_ylabel("Average Tokens per Generation")
    ax.set_title("Token Usage Comparison Across LLMs", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out = output_dir / "multi_llm_token_usage.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_cost_comparison(data, output_dir):
    """Bar chart: cost per generation across models."""
    fig, ax = plt.subplots(figsize=(10, 6))

    models = sorted(set(r["model"] for r in data if r.get("model")))
    total_costs = []
    run_counts = []

    for model in models:
        costs = [r["cost_usd"] for r in data if r.get("model") == model and r.get("cost_usd") is not None]
        total = sum(costs)
        total_costs.append(total)
        run_counts.append(len(costs))

    bars = ax.bar(
        [DISPLAY_NAMES.get(m, m) for m in models],
        total_costs,
        color=[COLORS.get(m, "#888888") for m in models],
        alpha=0.8, edgecolor="white", width=0.5,
    )

    for bar, cost, n in zip(bars, total_costs, run_counts):
        label = f"${cost:.4f}" if cost > 0 else "Free"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(total_costs) * 0.02,
               f"{label}\n({n} runs)", ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax.set_ylabel("Total API Cost (USD)")
    ax.set_title("Total LLM API Cost Comparison", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out = output_dir / "multi_llm_cost.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_combined_summary(data, output_dir):
    """Combined 2x2 grid: time, success, tokens, cost."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    models = sorted(set(r["model"] for r in data if r.get("model")))
    display = [DISPLAY_NAMES.get(m, m) for m in models]
    colors = [COLORS.get(m, "#888888") for m in models]

    # Top-left: Generation time
    ax = axes[0, 0]
    times = []
    for model in models:
        t = [r["duration_secs"] for r in data if r.get("model") == model and r.get("duration_secs")]
        times.append(sum(t) / len(t) if t else 0)
    ax.bar(display, times, color=colors, alpha=0.8, edgecolor="white")
    for i, v in enumerate(times):
        ax.text(i, v + 0.3, f"{v:.1f}s", ha="center", fontweight="bold", fontsize=10)
    ax.set_ylabel("Avg Generation Time (s)")
    ax.set_title("Generation Speed", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    # Top-right: Success rate
    ax = axes[0, 1]
    rates = []
    for model in models:
        runs = [r for r in data if r.get("model") == model]
        success = sum(1 for r in runs if r.get("generation_success") == 1)
        rates.append(success / len(runs) * 100 if runs else 0)
    ax.bar(display, rates, color=colors, alpha=0.8, edgecolor="white")
    for i, v in enumerate(rates):
        ax.text(i, v + 1, f"{v:.0f}%", ha="center", fontweight="bold", fontsize=10)
    ax.set_ylabel("Success Rate (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Structural Generation Success", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    # Bottom-left: Token usage
    ax = axes[1, 0]
    tokens = []
    for model in models:
        t = [r["tokens_total"] for r in data if r.get("model") == model and r.get("tokens_total")]
        tokens.append(sum(t) / len(t) if t else 0)
    ax.bar(display, tokens, color=colors, alpha=0.8, edgecolor="white")
    for i, v in enumerate(tokens):
        ax.text(i, v + 50, f"{v:.0f}", ha="center", fontweight="bold", fontsize=10)
    ax.set_ylabel("Avg Tokens per Call")
    ax.set_title("Token Usage", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    # Bottom-right: Cost
    ax = axes[1, 1]
    costs = []
    for model in models:
        c = [r["cost_usd"] for r in data if r.get("model") == model and r.get("cost_usd")]
        costs.append(sum(c) / len(c) if c else 0)
    ax.bar(display, costs, color=colors, alpha=0.8, edgecolor="white")
    for i, v in enumerate(costs):
        label = f"${v:.5f}" if v > 0 else "Free"
        ax.text(i, v + max(costs) * 0.05, label, ha="center", fontweight="bold", fontsize=10)
    ax.set_ylabel("Avg Cost per Call (USD)")
    ax.set_title("API Cost", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Multi-LLM Comparison: GPT-3.5 vs Gemini vs Claude", fontsize=16, fontweight="bold", y=1.02)
    plt.tight_layout()
    out = output_dir / "multi_llm_combined_summary.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"  Saved: {out}")


def print_summary_table(data):
    """Print a text summary table."""
    models = sorted(set(r["model"] for r in data if r.get("model")))

    print(f"\n{'='*80}")
    print(f"  MULTI-LLM COMPARISON SUMMARY")
    print(f"{'='*80}")
    print(f"  {'Model':<22} {'Runs':>5} {'Success':>10} {'Avg Time':>10} {'Avg Tokens':>11} {'Avg Cost':>12}")
    print(f"  {'─'*72}")

    for model in models:
        display = DISPLAY_NAMES.get(model, model)
        runs = [r for r in data if r.get("model") == model]
        n = len(runs)
        success = sum(1 for r in runs if r.get("generation_success") == 1)
        avg_time = sum(r.get("duration_secs", 0) or 0 for r in runs) / max(n, 1)
        avg_tokens = sum(r.get("tokens_total", 0) or 0 for r in runs) / max(n, 1)
        avg_cost = sum(r.get("cost_usd", 0) or 0 for r in runs) / max(n, 1)

        rate = f"{success}/{n} ({success/n*100:.0f}%)" if n > 0 else "N/A"
        cost_str = f"${avg_cost:.5f}" if avg_cost > 0 else "Free"

        print(f"  {display:<22} {n:>5} {rate:>10} {avg_time:>9.1f}s {avg_tokens:>10.0f} {cost_str:>12}")


def main():
    setup_style()

    parser = argparse.ArgumentParser(description="Generate multi-LLM comparison charts")
    parser.add_argument("--csv", default=str(COMPARISON_CSV))
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    data = load_data(Path(args.csv))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loaded {len(data)} rows from {args.csv}")
    print(f"Generating charts to {output_dir}/\n")

    print_summary_table(data)

    plot_generation_time(data, output_dir)
    plot_success_rate(data, output_dir)
    plot_token_usage(data, output_dir)
    plot_cost_comparison(data, output_dir)
    plot_combined_summary(data, output_dir)

    print(f"\nDone. All charts saved to {output_dir}/")


if __name__ == "__main__":
    main()
