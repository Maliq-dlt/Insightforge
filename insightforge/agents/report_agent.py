from __future__ import annotations

from typing import Any


class ReportAgent:
    def render(self, question: str, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        answer_type = plan.get("answer_type", "aggregate")
        if answer_type == "comparison":
            return self._comparison(question, evidence)
        if answer_type == "quality":
            return self._quality(question, evidence)
        if evidence and len(evidence[0].get("rows", [])) > 1:
            return self._grouped(question, evidence[0])
        return self._aggregate(question, evidence[0] if evidence else {})

    @staticmethod
    def _aggregate(question: str, evidence: dict[str, Any]) -> str:
        rows = evidence.get("rows", [])
        row = rows[0] if rows else {}
        value = row.get("metric_value", row.get("row_count"))
        non_null = row.get("non_null_count")
        lines = ["## Jawaban", f"Untuk pertanyaan **{question}**, hasil terukur adalah **{value}**."]
        if non_null is not None:
            lines.append(f"Nilai non-null yang dipakai: **{non_null}**.")
        lines.extend(
            [
                "",
                f"Evidence: `{evidence.get('id', 'unknown')}` [evidence:{evidence.get('key', 'aggregate')}].",
                "Batasan: hasil mengikuti definisi kolom dan filter yang tersedia pada dataset.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _grouped(question: str, evidence: dict[str, Any]) -> str:
        rows = evidence.get("rows", [])
        top_rows = rows[:3]
        bullets = [f"- `{row.get('segment')}`: **{row.get('metric_value')}**" for row in top_rows]
        return "\n".join(
            [
                "## Jawaban",
                f"Untuk pertanyaan **{question}**, segmen teratas:",
                *bullets,
                "",
                f"Evidence: `{evidence.get('id', 'unknown')}` [evidence:{evidence.get('key', 'grouped_aggregate')}].",
                f"Total segmen yang dikembalikan: **{len(rows)}**.",
                "Batasan: ranking bukan bukti kausal.",
            ]
        )

    @staticmethod
    def _comparison(question: str, evidence: list[dict[str, Any]]) -> str:
        monthly = next((item for item in evidence if item.get("key") == "monthly_comparison"), {})
        segments = next((item for item in evidence if item.get("key") == "segment_contribution"), {})
        monthly_rows = monthly.get("rows", [])
        change_line = "Perbandingan bulan tidak menghasilkan baris."
        if len(monthly_rows) >= 2:
            previous, current = monthly_rows[0], monthly_rows[-1]
            previous_value = float(previous.get("metric_value") or 0)
            current_value = float(current.get("metric_value") or 0)
            change = current_value - previous_value
            rate = change / previous_value if previous_value else None
            change_line = f"Nilai berubah dari **{previous_value:g}** menjadi **{current_value:g}**"
            if rate is not None:
                change_line += f" (**{rate:.1%}**)."
            else:
                change_line += "."
        top_segment = (segments.get("rows") or [{}])[0]
        segment_line = "Kontribusi segmen tidak tersedia."
        if top_segment:
            segment_line = (
                f"Penurunan terbesar pada hasil segmentasi: **{top_segment.get('segment')}** "
                f"dengan delta **{top_segment.get('delta')}**."
            )
        return "\n".join(
            [
                "## Jawaban",
                f"Untuk pertanyaan **{question}**:",
                f"- {change_line} [evidence:monthly_comparison]",
                f"- {segment_line} [evidence:segment_contribution]",
                "",
                "Metode: agregasi read-only per periode dan segmentasi; bukan uji kausal.",
                "Batasan: analisis belum mengontrol seasonality, campaign, atau confounder lain.",
            ]
        )

    @staticmethod
    def _quality(question: str, evidence: list[dict[str, Any]]) -> str:
        rows = evidence[0].get("rows", []) if evidence else []
        risky = [row for row in rows if float(row.get("missing_rate") or 0) > 0]
        lines = [
            "## Jawaban",
            f"Untuk pertanyaan **{question}**, {len(risky)} kolom memiliki missing value.",
        ]
        for row in risky[:5]:
            lines.append(f"- `{row.get('column')}`: **{row.get('missing_rate'):.1%}**")
        lines.extend(["", "Evidence: [evidence:missing_values].", "Batasan: missing tidak otomatis berarti data invalid."])
        return "\n".join(lines)
