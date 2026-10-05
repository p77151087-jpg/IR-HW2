"""Small, data-driven comparisons for the HW2 display and report figures.

Read saved analysis results without changing tokenization or recalculating fits.
"""
from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .analysis import _term_rows

COLORS = {"A": "#355C9A", "B": "#16847D", "C": "#C87924", "D": "#9152A0"}
SEGMENTS = {"head": "高頻", "middle": "中頻", "tail": "低頻"}
SEGMENT_COLORS = ["#6685AD", "#16847D", "#D99750"]
METRICS = {"tokens": "總出現次數（tokens）", "unique_terms": "不同詞數", "postings_entries": "詞－文件配對數（ΣDF）"}


def preprocessing_rows(summary):
    return [{"condition": c, "metric": key, "value": data[key]}
            for c, data in summary["conditions"].items() for key in METRICS]


def top_term_rows(summary, limit=10):
    return [{"condition": c, **row} for c, data in summary["conditions"].items()
            for row in data["top50"][:limit]]


def segment_rows(summary):
    return [{"condition": c, "segment": name, **fit}
            for c, data in summary["conditions"].items()
            for name, fit in data["segments"].items()]


def best_segments(summary):
    """Only call a segment best when it maximizes R² and minimizes RMSE."""
    rows = []
    for c, data in summary["conditions"].items():
        valid = {name: fit for name, fit in data["segments"].items()
                 if fit["r_squared"] is not None and fit["rmse"] is not None}
        if not valid:
            rows.append({"condition": c, "best": [], "status": "insufficient"})
            continue
        r2 = max(fit["r_squared"] for fit in valid.values())
        rmse = min(fit["rmse"] for fit in valid.values())
        best = [name for name, fit in valid.items()
                if math.isclose(fit["r_squared"], r2, abs_tol=1e-12)
                and math.isclose(fit["rmse"], rmse, abs_tol=1e-12)]
        rows.append({"condition": c, "best": best, "status": "agreed" if best else "mixed"})
    return rows


def selected_term_rows(summary):
    rows = []
    for row in summary["selected_terms"]:
        n = summary["conditions"][row["condition"]]["documents"]
        rows.append({**row, "coverage": row["df"] / n,
                     "occurrences_per_document": row["cf"] / row["df"]})
    return rows


def all_term_rows(summary):
    """Use the same saved B counts and IDF function as the experiment CSV."""
    return [{"condition": "B", **row} for row in _term_rows(summary["conditions"]["B"])]


def frequency_bubbles(rows, coordinates):
    """Aggregate every term, keeping at most five deterministic hover examples."""
    grouped = {}
    for row in rows:
        key = tuple(row[field] for field in coordinates)
        if key not in grouped:
            grouped[key] = {field: row[field] for field in coordinates}
            grouped[key].update(idf=row["idf"], term_count=0, examples=[])
        bubble = grouped[key]
        bubble["term_count"] += 1
        if len(bubble["examples"]) < 5:
            bubble["examples"].append(row["term"])
    return [{**bubble, "examples": "、".join(bubble["examples"])}
            for bubble in sorted(grouped.values(), key=lambda item: -item["term_count"])]


def _bubble_size(bubbles):
    maximum = max(row["term_count"] for row in bubbles)
    values = sorted({1, max(1, round(maximum / 4)), max(1, round(maximum / 2)), maximum})
    # Size is pixel area. A small floor keeps rare coordinates visible/clickable;
    # the linear scale and explicit legend retain the quantitative count mapping.
    return alt.Size("term_count:Q", title="詞數（氣泡面積）",
                    scale=alt.Scale(type="linear", domain=[0, max(20, maximum)], range=[24, 1600]),
                    legend=alt.Legend(orient="bottom", direction="horizontal", values=values,
                                      format=",.0f", titleLimit=220, labelOverlap=False))


def representative_terms(summary, limit=12):
    rows = selected_term_rows(summary)
    preferred = ["and", "the", "receptor", "glp-1", "semaglutide", "insulin",
                 "not", "no", "without", "il6", "pathway-specific", "endotyping"]
    by_term = {row["term"]: row for row in rows}
    chosen = [by_term[t] for t in preferred if t in by_term][:limit]
    chosen_terms = {row["term"] for row in chosen}
    chosen += [row for row in rows if row["term"] not in chosen_terms][:max(0, limit - len(chosen))]
    return sorted(chosen, key=lambda row: (row["idf"], row["term"]))


def _color():
    return alt.Color("condition:N", title="條件", scale=alt.Scale(domain=list(COLORS), range=list(COLORS.values())))


def count_chart(summary, metric):
    frame = pd.DataFrame([row for row in preprocessing_rows(summary) if row["metric"] == metric])
    base = alt.Chart(frame).encode(x=alt.X("condition:N", title="累積前處理條件", sort=list(COLORS), axis=alt.Axis(labelAngle=0)),
                                   y=alt.Y("value:Q", title=METRICS[metric], scale=alt.Scale(zero=True)))
    bars = base.mark_bar(size=58, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        color=_color(), tooltip=[alt.Tooltip("condition:N", title="條件"), alt.Tooltip("value:Q", title=METRICS[metric], format=",")])
    return (bars + base.mark_text(dy=-10).encode(text=alt.Text("value:Q", format=","))).properties(height=300)


def top_terms_chart(summary, condition, limit=15, shared_scale=False):
    frame = pd.DataFrame([row for row in top_term_rows(summary, limit) if row["condition"] == condition])
    scale = alt.Scale(zero=True)
    if shared_scale:
        scale = alt.Scale(domain=[0, max(row['cf'] for row in top_term_rows(summary, limit)) * 1.05])
    return alt.Chart(frame).mark_bar(color=COLORS[condition]).encode(
        x=alt.X("cf:Q", title="CF：全語料出現次數", scale=scale),
        y=alt.Y("term:N", title=None, sort=alt.SortField(field="rank", order="ascending"),
                axis=alt.Axis(labelOverlap=False, labelFontSize=12)),
        tooltip=["rank:Q", "term:N", "cf:Q", "df:Q", alt.Tooltip("idf:Q", format=".4f")]
    ).properties(height=max(230, min(len(frame), limit) * 23))


def segment_chart(summary, metric):
    frame = pd.DataFrame(segment_rows(summary))
    frame["區段"] = frame["segment"].map(SEGMENTS)
    title = "R²（越高越貼近直線）" if metric == "r_squared" else "RMSE（log CF；越低誤差越小）"
    scale = alt.Scale(domain=[0, 1]) if metric == "r_squared" else alt.Scale(zero=True)
    return alt.Chart(frame).mark_bar().encode(
        x=alt.X("condition:N", title="條件", sort=list(COLORS), axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("區段:N", sort=list(SEGMENTS.values())),
        y=alt.Y(f"{metric}:Q", title=title, scale=scale),
        color=alt.Color("區段:N", scale=alt.Scale(domain=list(SEGMENTS.values()), range=SEGMENT_COLORS)),
        tooltip=["condition:N", "區段:N", "rank_start:Q", "rank_end:Q",
                 alt.Tooltip("zipf_exponent:Q", title="指數 b", format=".4f"), alt.Tooltip(f"{metric}:Q", format=".4f")]
    ).properties(height=290)


def cf_df_chart(summary, rows=None):
    rows = all_term_rows(summary) if rows is None else rows
    bubbles = frequency_bubbles(rows, ("cf", "df"))
    if not bubbles:
        return None
    max_df = max(row["df"] for row in bubbles)
    reference = pd.DataFrame({"df": [1, max(2, max_df)], "cf": [1, max(2, max_df)]})
    encoding = dict(x=alt.X("df:Q", title="DF：出現於幾篇文件（log 刻度）",
                           scale=alt.Scale(type="log", base=10, domain=[.8, max(2, max_df) * 1.15]),
                           axis=alt.Axis(values=[1, 10, 100, 1000])),
                    y=alt.Y("cf:Q", title="CF：總出現次數（log 刻度）",
                           scale=alt.Scale(type="log", base=10, domain=[.7, max(row['cf'] for row in bubbles) * 1.5]),
                           axis=alt.Axis(values=[1, 10, 100, 1000, 10000])))
    line = alt.Chart(reference).mark_line(color="#8997A5", strokeDash=[5, 5]).encode(**encoding)
    # Explicit inline data avoids the DataFrame transformer's row cap even when
    # a future corpus has more than 5,000 distinct coordinates. Never sample.
    points = alt.Chart(alt.Data(values=bubbles)).mark_circle(color=COLORS["B"], opacity=0.58,
                                                           stroke="white", strokeWidth=0.4).encode(
        **encoding, size=_bubble_size(bubbles),
        tooltip=[alt.Tooltip("cf:Q", title="CF", format=","), alt.Tooltip("df:Q", title="DF", format=","),
                 alt.Tooltip("term_count:Q", title="詞數", format=","),
                 alt.Tooltip("examples:N", title="詞彙範例（最多 5 個）")])
    return (line + points).properties(height=390)


def idf_curve_chart(summary, rows=None):
    rows = all_term_rows(summary) if rows is None else rows
    bubbles = frequency_bubbles(rows, ("df",))
    if not bubbles:
        return None
    n = summary["conditions"]["B"]["documents"]
    # Log-spaced sampling keeps the plot small even for a larger saved corpus.
    dfs = sorted({1, n, *(max(1, round(n ** (i / 160))) for i in range(161))})
    curve = pd.DataFrame({"df": dfs, "idf": [math.log10(n / df) for df in dfs]})
    encoding = dict(x=alt.X("df:Q", title="DF：文件覆蓋數（log 刻度）",
                           scale=alt.Scale(type="log", base=10, domain=[.7, max(2, n) * 1.35]),
                           axis=alt.Axis(values=[1, 10, 100, 1000])),
                    y=alt.Y("idf:Q", title="IDF = log(N / DF)",
                            scale=alt.Scale(domain=[-0.15, max(.1, math.log10(n)) + .2])))
    line = alt.Chart(curve).mark_line(color="#ABB5C0").encode(**encoding)
    points = alt.Chart(alt.Data(values=bubbles)).mark_circle(color=COLORS["B"], opacity=0.58,
                                                           stroke="white", strokeWidth=0.4).encode(
        **encoding, size=_bubble_size(bubbles),
        tooltip=[alt.Tooltip("df:Q", title="DF", format=","), alt.Tooltip("idf:Q", title="IDF", format=".4f"),
                 alt.Tooltip("term_count:Q", title="詞數", format=","),
                 alt.Tooltip("examples:N", title="詞彙範例（最多 5 個）")])
    return (line + points).properties(height=370)


def idf_terms_chart(summary):
    frame = pd.DataFrame(representative_terms(summary))
    return alt.Chart(frame).mark_bar(color=COLORS["B"]).encode(
        x=alt.X("idf:Q", title="IDF = log(N / DF)"),
        y=alt.Y("term:N", title=None, sort=frame["term"].tolist()),
        tooltip=["term:N", "cf:Q", "df:Q", alt.Tooltip("idf:Q", format=".4f")]
    ).properties(height=max(240, len(frame) * 27))
