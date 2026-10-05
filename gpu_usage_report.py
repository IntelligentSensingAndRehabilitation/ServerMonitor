#!/usr/bin/env python3
"""GPU usage report.

Queries Prometheus (via Grafana's datasource proxy, since Prometheus
isn't exposed to the host) and produces 4 plots + a text summary
answering: are the GPUs becoming resource-limited?

Usage:
    python3 gpu_usage_report.py                   # last 30 days
    python3 gpu_usage_report.py --days 7
    python3 gpu_usage_report.py --output-dir /tmp/report
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import requests


HERE = Path(__file__).resolve().parent

UTIL_SATURATED_PCT = 80
UTIL_HEAVY_PCT = 95
MEM_SATURATED_PCT = 90
MEM_HEAVY_PCT = 95


def load_env(env_path: Path) -> dict:
    if not env_path.exists():
        raise FileNotFoundError(f"Missing .env file at {env_path}")
    out = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def make_session(grafana_port: str) -> tuple[requests.Session, str]:
    session = requests.Session()
    base = f"http://localhost:{grafana_port}/api/datasources/proxy/uid/prometheus"
    return session, base


def query_range(session, base_url, query, start, end, step):
    resp = session.get(
        f"{base_url}/api/v1/query_range",
        params={
            "query": query,
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "step": step,
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if body["status"] != "success":
        raise RuntimeError(f"Prometheus query failed: {body}")
    return body["data"]["result"]


def query_instant(session, base_url, query):
    resp = session.get(
        f"{base_url}/api/v1/query",
        params={"query": query},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if body["status"] != "success":
        raise RuntimeError(f"Prometheus query failed: {body}")
    return body["data"]["result"]


def to_arrays(result):
    """Convert query_range result to {gpu_id: (timestamps, values)}."""
    out = {}
    for series in result:
        gpu = series["metric"].get("gpu", "0")
        timestamps = np.array([float(v[0]) for v in series["values"]])
        values = np.array([float(v[1]) for v in series["values"]])
        out[gpu] = (timestamps, values)
    return out


def percent_above(values: np.ndarray, threshold: float) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.mean(values > threshold) * 100)


def hour_of_day(timestamps: np.ndarray) -> np.ndarray:
    return np.array([dt.datetime.fromtimestamp(ts).hour for ts in timestamps])


def day_of_week(timestamps: np.ndarray) -> np.ndarray:
    return np.array([dt.datetime.fromtimestamp(ts).weekday() for ts in timestamps])


def configure_matplotlib():
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 12,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
    })


def plot_saturation_summary(util_data, mem_data, out_path: Path):
    gpus = sorted(util_data.keys(), key=lambda x: int(x) if x.isdigit() else x)
    util_pct = [percent_above(util_data[g][1], UTIL_SATURATED_PCT) for g in gpus]
    mem_pct = [percent_above(mem_data[g][1], MEM_SATURATED_PCT) for g in gpus]

    fig, ax = plt.subplots(figsize=(10, max(4, 0.6 * len(gpus) + 2)))
    y = np.arange(len(gpus))
    bar_h = 0.38
    ax.barh(y - bar_h / 2, util_pct, bar_h, label=f"% time at >{UTIL_SATURATED_PCT}% utilization", color="#d62728")
    ax.barh(y + bar_h / 2, mem_pct, bar_h, label=f"% time at >{MEM_SATURATED_PCT}% memory", color="#1f77b4")
    ax.set_yticks(y)
    ax.set_yticklabels([f"GPU {g}" for g in gpus])
    ax.set_xlabel("% of time")
    ax.set_xlim(0, 100)
    ax.set_title("Resource Saturation Summary\nHow often is each GPU compute-saturated vs memory-saturated?")
    ax.legend(loc="lower right")
    for i, v in enumerate(util_pct):
        ax.text(v + 1, i - bar_h / 2, f"{v:.1f}%", va="center", fontsize=9)
    for i, v in enumerate(mem_pct):
        ax.text(v + 1, i + bar_h / 2, f"{v:.1f}%", va="center", fontsize=9)
    fig.savefig(out_path)
    plt.close(fig)


def plot_daily_pattern(util_data, out_path: Path):
    all_hours = []
    all_values = []
    for ts, vals in util_data.values():
        all_hours.append(hour_of_day(ts))
        all_values.append(vals)
    hours = np.concatenate(all_hours)
    values = np.concatenate(all_values)

    means = np.array([values[hours == h].mean() if (hours == h).any() else np.nan for h in range(24)])
    stds = np.array([values[hours == h].std() if (hours == h).any() else np.nan for h in range(24)])

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(24)
    ax.plot(x, means, color="#1f77b4", linewidth=2, label="Mean utilization")
    ax.fill_between(x, np.maximum(means - stds, 0), np.minimum(means + stds, 100),
                    color="#1f77b4", alpha=0.2, label="±1 std dev")
    ax.set_xticks(np.arange(0, 24, 3))
    ax.set_xticklabels([f"{h:02d}:00" for h in np.arange(0, 24, 3)])
    ax.set_xlabel("Hour of day (server local time)")
    ax.set_ylabel("GPU utilization (%)")
    ax.set_title("Average GPU Utilization by Hour of Day\n(Flat-and-high → continuous saturation; spiky → workload-bound)")
    ax.set_ylim(0, 100)
    ax.legend()
    fig.savefig(out_path)
    plt.close(fig)


def plot_weekly_heatmap(util_data, out_path: Path):
    all_hours = []
    all_dows = []
    all_values = []
    for ts, vals in util_data.values():
        all_hours.append(hour_of_day(ts))
        all_dows.append(day_of_week(ts))
        all_values.append(vals)
    hours = np.concatenate(all_hours)
    dows = np.concatenate(all_dows)
    values = np.concatenate(all_values)

    grid = np.full((7, 24), np.nan)
    for d in range(7):
        for h in range(24):
            mask = (dows == d) & (hours == h)
            if mask.any():
                grid[d, h] = values[mask].mean()

    fig, ax = plt.subplots(figsize=(13, 4.5))
    im = ax.imshow(grid, aspect="auto", cmap="YlOrRd", vmin=0, vmax=100)
    ax.set_yticks(np.arange(7))
    ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(np.arange(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}" for h in np.arange(0, 24, 2)])
    ax.set_xlabel("Hour of day")
    ax.set_title("GPU Utilization Heatmap: Day of Week × Hour\n(Reveals weekday/weekend patterns and structural vs bursty load)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Avg utilization (%)")
    ax.grid(False)
    fig.savefig(out_path)
    plt.close(fig)


def plot_per_gpu_distribution(util_data, out_path: Path):
    gpus = sorted(util_data.keys(), key=lambda x: int(x) if x.isdigit() else x)
    data = [util_data[g][1] for g in gpus]

    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(gpus) + 2), 5))
    parts = ax.violinplot(data, showmeans=True, showmedians=False, widths=0.8)
    for pc in parts["bodies"]:
        pc.set_facecolor("#1f77b4")
        pc.set_alpha(0.6)
    ax.set_xticks(np.arange(1, len(gpus) + 1))
    ax.set_xticklabels([f"GPU {g}" for g in gpus])
    ax.set_ylabel("Utilization (%)")
    ax.set_ylim(-5, 105)
    ax.set_title("Per-GPU Utilization Distribution\n(Even distributions = balanced load; one-GPU saturation = scheduling issue)")
    fig.savefig(out_path)
    plt.close(fig)


def build_summary(util_data, mem_data, days, start, end):
    gpus = sorted(util_data.keys(), key=lambda x: int(x) if x.isdigit() else x)

    all_util = np.concatenate([util_data[g][1] for g in gpus])
    all_mem = np.concatenate([mem_data[g][1] for g in gpus])

    fleet_avg_util = float(all_util.mean())
    fleet_peak_util = float(all_util.max())
    pct_util_saturated = percent_above(all_util, UTIL_SATURATED_PCT)
    pct_util_heavy = percent_above(all_util, UTIL_HEAVY_PCT)
    fleet_avg_mem = float(all_mem.mean())
    pct_mem_saturated = percent_above(all_mem, MEM_SATURATED_PCT)
    pct_mem_heavy = percent_above(all_mem, MEM_HEAVY_PCT)

    per_gpu_avg_util = {g: float(util_data[g][1].mean()) for g in gpus}
    per_gpu_avg_mem = {g: float(mem_data[g][1].mean()) for g in gpus}
    per_gpu_active_hrs = {
        g: float(np.mean(util_data[g][1] > 10) * 24) for g in gpus
    }

    util_values = list(per_gpu_avg_util.values())
    util_max = max(util_values)
    util_min = max(min(util_values), 0.1)
    util_imbalance_ratio = util_max / util_min

    if fleet_avg_util < 30 and pct_util_saturated < 10:
        headline = "GPUs are UNDER-UTILIZED — current capacity is sufficient"
        recommendation = "No action needed. Capacity exceeds current workload."
    elif pct_mem_heavy > pct_util_heavy and pct_mem_saturated > 30:
        headline = "GPUs are MEMORY-LIMITED"
        recommendation = (
            "Memory saturates more often than compute. Consider GPUs with more VRAM "
            "or batch-size / model-size optimizations."
        )
    elif fleet_avg_util > 70 and pct_util_saturated > 30:
        headline = "GPUs are COMPUTE-LIMITED — approaching capacity"
        recommendation = (
            "Compute is saturated for a meaningful fraction of time. "
            "Consider adding GPU capacity or scheduling lower-priority work off-peak."
        )
    elif util_imbalance_ratio > 2.5 and len(gpus) > 1:
        headline = "GPUs are UNEVENLY LOADED — likely a scheduling issue"
        recommendation = (
            f"GPU avg utilization varies by {util_imbalance_ratio:.1f}× across the fleet. "
            "Investigate workload scheduling — capacity exists but isn't being used."
        )
    else:
        headline = "GPUs are WELL-UTILIZED — no immediate bottleneck"
        recommendation = "Capacity matches workload. Re-run this report periodically to track trends."

    lines = []
    lines.append("GPU UTILIZATION REPORT")
    lines.append("=" * 60)
    lines.append(f"Period: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')} ({days} days)")
    lines.append(f"GPUs analyzed: {len(gpus)}")
    lines.append("")
    lines.append(f"HEADLINE: {headline}")
    lines.append("")
    lines.append("KEY NUMBERS")
    lines.append(f"  Fleet average utilization:        {fleet_avg_util:5.1f}%")
    lines.append(f"  Fleet peak utilization:           {fleet_peak_util:5.1f}%")
    lines.append(f"  Time at >{UTIL_SATURATED_PCT}% utilization:          {pct_util_saturated:5.1f}% of GPU-hours")
    lines.append(f"  Time at >{UTIL_HEAVY_PCT}% utilization:          {pct_util_heavy:5.1f}% of GPU-hours")
    lines.append(f"  Fleet average memory:             {fleet_avg_mem:5.1f}%")
    lines.append(f"  Time at >{MEM_SATURATED_PCT}% memory:               {pct_mem_saturated:5.1f}% of GPU-hours")
    lines.append(f"  Time at >{MEM_HEAVY_PCT}% memory:               {pct_mem_heavy:5.1f}% of GPU-hours")
    lines.append("")
    lines.append("PER-GPU BREAKDOWN")
    for g in gpus:
        lines.append(
            f"  GPU {g}: avg {per_gpu_avg_util[g]:5.1f}% util | "
            f"avg {per_gpu_avg_mem[g]:5.1f}% mem | "
            f"~{per_gpu_active_hrs[g]:4.1f} active hrs/day"
        )
    lines.append("")
    lines.append("RECOMMENDATION")
    lines.append(f"  {recommendation}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default: 30)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Output directory (default: ./gpu_report_YYYY-MM-DD)")
    parser.add_argument("--step", default="5m", help="Query step (default: 5m)")
    parser.add_argument("--env", type=Path, default=HERE / ".env", help="Path to .env file")
    args = parser.parse_args()

    env = load_env(args.env)
    grafana_port = env["GRAFANA_PORT"]

    end = dt.datetime.now()
    start = end - dt.timedelta(days=args.days)

    out_dir = args.output_dir or HERE / f"gpu_report_{end.strftime('%Y-%m-%d')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Querying Prometheus via Grafana proxy at localhost:{grafana_port}")
    print(f"Window: {start} → {end} (step={args.step})")

    session, base = make_session(grafana_port)

    gpu_count = query_instant(session, base, "count(DCGM_FI_DEV_GPU_UTIL)")
    if not gpu_count:
        sys.exit("ERROR: No GPU metrics found. Is DCGM exporter running and producing data?")

    util_raw = query_range(session, base, "DCGM_FI_DEV_GPU_UTIL", start, end, args.step)
    mem_raw = query_range(
        session, base,
        "DCGM_FI_DEV_FB_USED / (DCGM_FI_DEV_FB_USED + DCGM_FI_DEV_FB_FREE) * 100",
        start, end, args.step,
    )

    util_data = to_arrays(util_raw)
    mem_data = to_arrays(mem_raw)

    if not util_data:
        sys.exit("ERROR: Utilization query returned no data.")

    print(f"Got {len(util_data)} GPU(s) of utilization data")

    configure_matplotlib()
    plot_saturation_summary(util_data, mem_data, out_dir / "saturation_summary.png")
    plot_daily_pattern(util_data, out_dir / "daily_pattern.png")
    plot_weekly_heatmap(util_data, out_dir / "weekly_heatmap.png")
    plot_per_gpu_distribution(util_data, out_dir / "per_gpu_distribution.png")

    summary = build_summary(util_data, mem_data, args.days, start, end)
    (out_dir / "summary.txt").write_text(summary + "\n")

    print()
    print(summary)
    print()
    print(f"Report saved to: {out_dir}")


if __name__ == "__main__":
    main()
