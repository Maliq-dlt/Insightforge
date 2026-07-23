from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def export_html_report(trace: dict[str, Any], output_path: Path) -> Path:
    analysis = trace["analysis"]
    result = analysis.get("result") or {}
    evidence = result.get("evidence", [])
    visualization = result.get("visualization")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _document(analysis, trace.get("steps", []), trace.get("evaluations", []), evidence, visualization),
        encoding="utf-8",
    )
    return output_path


def _document(
    analysis: dict[str, Any],
    steps: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    visualization: dict[str, Any] | None,
) -> str:
    answer = escape(str(analysis.get("final_answer") or analysis.get("error") or ""))
    plan = escape(json.dumps(analysis.get("plan") or {}, indent=2, ensure_ascii=False))
    evidence_html = "".join(_evidence_card(item) for item in evidence) or "<p>No evidence.</p>"
    step_html = "".join(
        f"<li><strong>{escape(str(step.get('sequence')))}. {escape(str(step.get('agent_name')))}</strong>"
        f"<span>{escape(str(step.get('status')))} · {escape(str(step.get('latency_ms')))} ms</span></li>"
        for step in steps
    )
    evaluation_html = "".join(
        f"<li><strong>{escape(str(item.get('evaluator')))}</strong>"
        f"<span>{float(item.get('score') or 0):.1%}</span></li>"
        for item in evaluations
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InsightForge report · {escape(str(analysis.get('id')))}</title>
<style>
:root {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #10201d; background: #edf4f1; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; }}
main {{ width: min(1080px, calc(100% - 32px)); margin: 32px auto; }}
header, section {{ background: white; border: 1px solid #cbdad5; border-radius: 16px; padding: 24px; margin: 16px 0; }}
h1, h2, h3 {{ margin-top: 0; }}
.meta {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
.meta div {{ background: #f4f8f6; border-radius: 10px; padding: 12px; }}
.meta span, li span {{ display: block; color: #5e746e; font-size: 12px; margin-top: 4px; }}
.answer {{ white-space: pre-wrap; line-height: 1.6; }}
pre {{ overflow: auto; background: #0b1714; color: #d9eee7; padding: 14px; border-radius: 10px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #dbe7e3; padding: 8px; text-align: left; }}
ul {{ padding-left: 20px; }}
li {{ margin: 8px 0; }}
.chart {{ overflow-x: auto; }}
@media print {{ body {{ background: white; }} main {{ width: 100%; margin: 0; }} header, section {{ break-inside: avoid; box-shadow: none; }} }}
@media (max-width: 720px) {{ .meta {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>
<main>
<header>
<p>INSIGHTFORGE · AUDITABLE ANALYSIS</p>
<h1>{escape(str(analysis.get('question')))}</h1>
<div class="meta">
<div><strong>Analysis</strong><span>{escape(str(analysis.get('id')))}</span></div>
<div><strong>Status</strong><span>{escape(str(analysis.get('status')))}</span></div>
<div><strong>Mode</strong><span>{escape(str(analysis.get('mode')))}</span></div>
<div><strong>Completed</strong><span>{escape(str(analysis.get('completed_at') or '—'))}</span></div>
</div>
</header>
<section><h2>Finding</h2><div class="answer">{answer}</div></section>
<section><h2>Visualization</h2><div class="chart">{_chart(visualization)}</div></section>
<section><h2>Evidence and SQL</h2>{evidence_html}</section>
<section><h2>Execution plan</h2><pre>{plan}</pre></section>
<section><h2>Trace</h2><ul>{step_html}</ul></section>
<section><h2>Evaluations</h2><ul>{evaluation_html or '<li>No evaluations.</li>'}</ul></section>
</main>
</body>
</html>"""


def _evidence_card(item: dict[str, Any]) -> str:
    return (
        f"<article><h3>{escape(str(item.get('purpose')))}</h3>"
        f"<p><code>{escape(str(item.get('key')))}</code> · {escape(str(item.get('row_count')))} rows</p>"
        f"<pre>{escape(str(item.get('sql') or ''))}</pre>{_table(item.get('rows', []))}</article>"
    )


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No rows returned.</p>"
    columns = list(rows[0])
    head = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _chart(spec: dict[str, Any] | None) -> str:
    points = (spec or {}).get("points", [])
    if not points:
        return "<p>No chart for this result.</p>"
    width, height, left, bottom = 720, 320, 50, 55
    plot_width, plot_height = width - left - 20, height - 25 - bottom
    values = [float(point.get("y") or 0) for point in points]
    domain_min, domain_max = min(0.0, *values), max(0.0, *values)
    span = domain_max - domain_min or 1.0

    def y(value: float) -> float:
        return 25 + (domain_max - value) / span * plot_height

    zero_y = y(0)
    slot = plot_width / len(points)
    bars = []
    for index, point in enumerate(points):
        value = float(point.get("y") or 0)
        center = left + slot * index + slot / 2
        value_y = y(value)
        bar_y = min(value_y, zero_y)
        bar_height = max(2.0, abs(zero_y - value_y))
        color = "#d6a83a" if value < 0 else "#19a974"
        bars.append(
            f'<rect x="{center - slot * 0.29:.1f}" y="{bar_y:.1f}" width="{slot * 0.58:.1f}" '
            f'height="{bar_height:.1f}" rx="6" fill="{color}"/>'
            f'<text x="{center:.1f}" y="{height - 25}" text-anchor="middle" font-size="11">'
            f'{escape(str(point.get("x") or ""))}</text>'
            f'<text x="{center:.1f}" y="{max(15, value_y - 7):.1f}" text-anchor="middle" font-size="11">'
            f'{value:g}</text>'
        )
    alt = escape(str((spec or {}).get("alt_text") or "Evidence chart"))
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{alt}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{left}" x2="{width - 20}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="#9bb0aa"/>'
        + "".join(bars)
        + "</svg>"
    )