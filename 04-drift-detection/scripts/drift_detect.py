"""Drift detection on a synthetic AI input dataset.

Reference: 1000 rows of (prompt_length, embedding_norm, response_length,
response_quality). Current: 1000 rows with deliberate shift on prompt_length
and response_quality.

Outputs:
  reports/drift-report.html
  reports/drift-summary.json

The lab originally used numpy/pandas/scipy/evidently. This CLI keeps the same
outputs but uses only the Python standard library so it runs cleanly on a fresh
Windows host.
"""
from __future__ import annotations

import csv
import html
import json
import math
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"
REPORTS_DIR = HERE / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)


def synth_dataset(rng: random.Random, *, shifted: bool) -> dict[str, list[float]]:
    n = 1000
    rows = {
        "prompt_length": [],
        "embedding_norm": [],
        "response_length": [],
        "response_quality": [],
    }
    for _ in range(n):
        if shifted:
            rows["prompt_length"].append(rng.gauss(85, 20))
            rows["embedding_norm"].append(rng.gauss(1.0, 0.1))
            rows["response_length"].append(rng.gauss(120, 40))
            rows["response_quality"].append(rng.betavariate(2, 6))
        else:
            rows["prompt_length"].append(rng.gauss(50, 15))
            rows["embedding_norm"].append(rng.gauss(1.0, 0.1))
            rows["response_length"].append(rng.gauss(120, 40))
            rows["response_quality"].append(rng.betavariate(8, 2))
    return rows


def write_csv(path: Path, data: dict[str, list[float]]) -> None:
    columns = list(data)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for i in range(len(data[columns[0]])):
            writer.writerow([round(data[col][i], 6) for col in columns])


def histogram(reference: list[float], current: list[float], bins: int) -> tuple[list[int], list[int]]:
    lo = min(min(reference), min(current))
    hi = max(max(reference), max(current))
    width = (hi - lo) / bins or 1.0
    ref_hist = [0] * bins
    cur_hist = [0] * bins
    for values, hist in ((reference, ref_hist), (current, cur_hist)):
        for value in values:
            idx = min(bins - 1, max(0, int((value - lo) / width)))
            hist[idx] += 1
    return ref_hist, cur_hist


def population_stability_index(reference: list[float], current: list[float], bins: int = 10) -> float:
    ref_hist, cur_hist = histogram(reference, current, bins)
    ref_total = sum(ref_hist) + bins
    cur_total = sum(cur_hist) + bins
    psi = 0.0
    for ref_count, cur_count in zip(ref_hist, cur_hist):
        ref_p = (ref_count + 1) / ref_total
        cur_p = (cur_count + 1) / cur_total
        psi += (cur_p - ref_p) * math.log(cur_p / ref_p)
    return psi


def kl_divergence(reference: list[float], current: list[float], bins: int = 20) -> float:
    ref_hist, cur_hist = histogram(reference, current, bins)
    ref_total = sum(ref_hist) + (1e-9 * bins)
    cur_total = sum(cur_hist) + (1e-9 * bins)
    kl = 0.0
    for ref_count, cur_count in zip(ref_hist, cur_hist):
        ref_p = (ref_count + 1e-9) / ref_total
        cur_p = (cur_count + 1e-9) / cur_total
        kl += ref_p * math.log(ref_p / cur_p)
    return kl


def ks_2samp(reference: list[float], current: list[float]) -> tuple[float, float]:
    ref = sorted(reference)
    cur = sorted(current)
    i = j = 0
    n_ref = len(ref)
    n_cur = len(cur)
    max_delta = 0.0
    while i < n_ref and j < n_cur:
        value = ref[i] if ref[i] <= cur[j] else cur[j]
        while i < n_ref and ref[i] <= value:
            i += 1
        while j < n_cur and cur[j] <= value:
            j += 1
        max_delta = max(max_delta, abs(i / n_ref - j / n_cur))
    effective_n = n_ref * n_cur / (n_ref + n_cur)
    p_value = min(1.0, 2.0 * math.exp(-2.0 * effective_n * max_delta * max_delta))
    return max_delta, p_value


def write_html_report(path: Path, summary: dict[str, dict[str, float | str]]) -> None:
    rows = []
    for feature, metrics in summary.items():
        rows.append(
            "<tr>"
            f"<td>{html.escape(feature)}</td>"
            f"<td>{metrics['psi']}</td>"
            f"<td>{metrics['kl']}</td>"
            f"<td>{metrics['ks_stat']}</td>"
            f"<td>{metrics['ks_pvalue']}</td>"
            f"<td>{html.escape(str(metrics['drift']))}</td>"
            "</tr>"
        )
    path.write_text(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Day 23 Drift Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 2rem; color: #1f2937; }
    table { border-collapse: collapse; width: 100%; max-width: 920px; }
    th, td { border: 1px solid #d1d5db; padding: 0.55rem 0.7rem; text-align: right; }
    th:first-child, td:first-child, th:last-child, td:last-child { text-align: left; }
    th { background: #f3f4f6; }
  </style>
</head>
<body>
  <h1>Day 23 Drift Report</h1>
  <p>PSI greater than 0.2 is flagged as drift; 0.1-0.2 is moderate.</p>
  <table>
    <thead><tr><th>Feature</th><th>PSI</th><th>KL</th><th>KS stat</th><th>KS p-value</th><th>Drift</th></tr></thead>
    <tbody>
"""
        + "\n".join(rows)
        + """
    </tbody>
  </table>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    rng = random.Random(42)
    reference = synth_dataset(rng, shifted=False)
    current = synth_dataset(rng, shifted=True)
    write_csv(DATA_DIR / "reference.csv", reference)
    write_csv(DATA_DIR / "current.csv", current)

    summary: dict[str, dict[str, float | str]] = {}
    for col in reference:
        psi = population_stability_index(reference[col], current[col])
        kl = kl_divergence(reference[col], current[col])
        ks_stat, ks_p = ks_2samp(reference[col], current[col])
        summary[col] = {
            "psi": round(psi, 4),
            "kl": round(kl, 4),
            "ks_stat": round(ks_stat, 4),
            "ks_pvalue": round(ks_p, 6),
            "drift": "yes" if psi > 0.2 else ("moderate" if psi > 0.1 else "no"),
        }

    summary_path = REPORTS_DIR / "drift-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    html_path = REPORTS_DIR / "drift-report.html"
    write_html_report(html_path, summary)

    print(f"Wrote: {summary_path}")
    for col, metrics in summary.items():
        print(
            f"  {col:<20} PSI={metrics['psi']:.3f}  "
            f"KL={metrics['kl']:.3f}  KS={metrics['ks_stat']:.3f}  "
            f"drift={metrics['drift']}"
        )
    print(f"Wrote: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
