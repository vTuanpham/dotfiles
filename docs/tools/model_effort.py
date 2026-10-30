"""Render a dated API effort curve from the public benchmark snapshot.

uv run --project agent-models python docs/tools/model_effort.py --model 'GPT-6.1 Sol'
"""

import argparse
import math
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from agent_models.benchmarks import number, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="exact published model name, without effort")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "flows/model-effort.svg")
    args = parser.parse_args()
    data = snapshot()
    source = data["sources"]["Artificial Analysis"]
    if source["status"] != "ok":
        raise ValueError("Artificial Analysis snapshot unavailable")
    points = []
    for table in source["tables"]:
        header = next((r for r in table if "Cost per Task USD" in r), None)
        if header is None:
            continue
        for row in table[table.index(header) + 1:]:
            match = re.fullmatch(re.escape(args.model) + r" \(([\w-]+)\)", row[header.index("Model")])
            if not match:
                continue
            score, cost, response = (row[header.index(field)] for field in (
                "Artificial Analysis Intelligence Index", "Cost per Task USD", "Total Response (s)"))
            if score in ("", "--") or cost in ("", "--"):
                continue
            points.append((match[1], number(score), number(cost.removeprefix("$")),
                           None if response in ("", "--") else number(response)))
    if not points or len({p[0] for p in points}) != len(points):
        raise ValueError("missing or duplicate isolated model/effort rows")
    points.sort(key=lambda p: p[2])
    max_cost = max(p[2] for p in points)
    if max_cost <= 0:
        raise ValueError("a cost curve needs a positive cost range")
    magnitude = 10 ** math.floor(math.log10(max_cost / 3))
    tick = next(magnitude * v for v in (1, 2, 5, 10) if magnitude * v >= max_cost / 3)
    x_max = math.ceil(max_cost / tick) * tick
    y_min = math.floor(min(p[1] for p in points) / 10) * 10
    y_max = max(y_min + 10, math.ceil(max(p[1] for p in points) / 10) * 10)
    height = max(460, 230 + len(points) * 38)
    bottom = height - 92
    def x(value):
        return 86 + value / x_max * 610

    def y(value):
        return bottom - (value - y_min) / (y_max - y_min) * (bottom - 136)
    retrieved = datetime.fromisoformat(data["retrieved"]).astimezone(UTC).strftime("%d %b %Y %H:%M UTC")
    version = ", ".join(source["metadata"])
    parts = [(f'<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="{height}" '
              f'viewBox="0 0 1040 {height}" role="img" aria-labelledby="title desc">'),
             f'<title id="title">{escape(args.model)} measured effort curve</title>',
             ('<desc id="desc">Observed index against API USD per task; response time is '
              'not agent task duration. Source and retrieval time are recorded on the figure.</desc>'),
             f'<rect width="1040" height="{height}" fill="#faf9f6"/>',
             '<g font-family="Arial, Helvetica, sans-serif" fill="#263733">']

    def text(px, py, value, size=13, color="#263733", anchor="start", extra=""):
        parts.append(f'<text x="{px:g}" y="{py:g}" font-size="{size}" fill="{color}" '
                     f'text-anchor="{anchor}" {extra}>{escape(str(value))}</text>')

    text(36, 38, "MEASURED EFFORT CURVE · " + args.model, 11, "#68766f", extra='letter-spacing="2"')
    text(36, 78, "Measured effort, quality and cost.", 30, extra='font-family="Georgia, serif"')
    text(36, 105, f"Artificial Analysis · {version} · retrieved {retrieved}", 12, "#68766f")
    for value in range(y_min, y_max + 1, 10):
        parts.append(f'<path d="M86 {y(value):g}H696" stroke="#e2e5df"/>')
        text(65, y(value) + 4, value, 12, "#68766f", "end")
    parts.append(f'<path d="M86 136V{bottom}H696" stroke="#a4ada7" fill="none"/>')
    text(86, 126, "Index ↑", 12, "#68766f")
    for i in range(round(x_max / tick) + 1):
        text(x(i * tick), bottom + 24, f"${i * tick:g}", 12, "#68766f", "middle")
    text(390, bottom + 49, "API USD per task →", 12, "#68766f", "middle")
    path = "M" + "L".join(f"{x(p[2]):g} {y(p[1]):g}" for p in points)
    parts.append(f'<path d="{path}" stroke="#8cae9c" stroke-width="1.8" fill="none"/>')
    text(761, 151, "Measured response", 16, extra='font-weight="700"')
    for i, (effort, score, cost, response) in enumerate(points):
        color = "#a35e43" if i == len(points) - 1 else "#23786f"
        parts.append(f'<circle cx="{x(cost):g}" cy="{y(score):g}" r="6" fill="{color}"/>')
        text(x(cost), y(score) - 17 if i % 2 else y(score) + 25, effort, 13, color, "middle")
        text(761, 193 + i * 38, effort, 14)
        text(1003, 193 + i * 38, f"{response:g} s" if response is not None else "unknown", 16,
             color, "end")
    parts.append(f'<path d="M733 136V{height - 82}" stroke="#d3d8d1"/>')
    text(761, height - 50, "Response time ≠ agent task duration", 12, "#68766f")
    text(36, height - 17, source["url"], 11, "#68766f")
    parts.append('</g>\n</svg>\n')
    args.output.write_text("\n".join(parts))
    print(args.output)


if __name__ == "__main__":
    main()
