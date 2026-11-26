"""
TOOL 3 - Chart & diagram generator (matplotlib, free, offline).

Turns small specs (decided by the agent) into PNG images:
  - render_chart():   bar / line / pie charts
  - render_diagram(): a process flow or a concept map

Images are returned as raw PNG bytes. The report stores them as base64 so the
same image shows up on the web page and inside the PDF.
"""

import base64
import io
import textwrap

import matplotlib

matplotlib.use("Agg")  # headless backend: no display needed
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# One calm, formal palette used everywhere.
PALETTE = ["#1e3a5f", "#3b6ea5", "#6c9bd2", "#94a3b8", "#475569", "#0f766e", "#b45309"]
INK = "#1f2937"


def _to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def to_data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _wrap(label: str, width: int) -> str:
    return "\n".join(textwrap.wrap(str(label), width=width)) or str(label)


# ------------------------------------------------------------------ charts

def render_chart(chart_type: str, title: str, labels: list[str], values: list[float],
                 x_label: str = "", y_label: str = "") -> bytes:
    """Render a bar, line or pie chart and return PNG bytes."""
    if len(labels) != len(values) or len(values) < 2:
        raise ValueError("Chart needs at least 2 matching labels and values")

    fig, ax = plt.subplots(figsize=(7, 4))
    wrapped = [_wrap(l, 14) for l in labels]

    if chart_type == "pie":
        _, texts, autotexts = ax.pie(
            values, labels=wrapped, autopct="%1.1f%%", startangle=90,
            colors=PALETTE * 3, textprops={"fontsize": 9, "color": INK},
            wedgeprops={"edgecolor": "white"}, pctdistance=0.72)
        for t in autotexts:
            t.set_color("white")
            t.set_fontweight("bold")
        ax.axis("equal")
    elif chart_type == "line":
        ax.plot(wrapped, values, marker="o", color=PALETTE[0], linewidth=2)
        for x, y in zip(wrapped, values):
            ax.annotate(f"{y:g}", (x, y), textcoords="offset points", xytext=(0, 7),
                        ha="center", fontsize=8, color=INK)
        ax.grid(axis="y", alpha=0.3)
    else:  # bar
        bars = ax.bar(wrapped, values, color=PALETTE[1], edgecolor=PALETTE[0])
        for rect, val in zip(bars, values):
            ax.annotate(f"{val:g}", (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                        textcoords="offset points", xytext=(0, 3), ha="center",
                        fontsize=8, color=INK)
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)

    if chart_type != "pie":
        ax.set_xlabel(x_label, fontsize=9, color=INK)
        ax.set_ylabel(y_label, fontsize=9, color=INK)
        ax.tick_params(labelsize=8, colors=INK)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    ax.set_title(_wrap(title, 60), fontsize=11, fontweight="bold", color=INK, pad=12)
    fig.tight_layout()
    return _to_png(fig)


# ---------------------------------------------------------------- diagrams

def _box(ax, cx, cy, w, h, text, fill, text_color="white", fontsize=9):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor=fill, edgecolor="none", zorder=3))
    ax.text(cx, cy, _wrap(text, 16), ha="center", va="center",
            fontsize=fontsize, color=text_color, fontweight="normal", zorder=4)


def _arrow(ax, x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=PALETTE[4], lw=1.6,
                                shrinkA=0, shrinkB=0))


def render_diagram(kind: str, title: str, nodes: list[str]) -> bytes:
    """
    kind = "flow"        -> boxes in sequence, left to right (wraps to rows)
    kind = "concept_map" -> first node in the centre, the rest around it
    """
    nodes = [n.strip() for n in nodes if n and n.strip()][:8]
    if len(nodes) < 3:
        raise ValueError("Diagram needs at least 3 nodes")

    if kind == "concept_map":
        import math
        fig, ax = plt.subplots(figsize=(7, 4.6))
        ax.set_xlim(-1.6, 1.6)
        ax.set_ylim(-1.1, 1.1)
        ax.axis("off")
        outer = nodes[1:]
        for i, label in enumerate(outer):
            ang = 2 * math.pi * i / len(outer) + math.pi / 2
            x, y = 1.1 * math.cos(ang), 0.78 * math.sin(ang)
            ax.plot([0, x], [0, y], color=PALETTE[3], lw=1.6, zorder=1)
            _box(ax, x, y, 0.78, 0.30, label, PALETTE[1])
        _box(ax, 0, 0, 0.95, 0.38, nodes[0], PALETTE[0], fontsize=10)
    else:  # flow
        per_row = 4
        rows = [nodes[i:i + per_row] for i in range(0, len(nodes), per_row)]
        fig, ax = plt.subplots(figsize=(7, 1.6 + 1.4 * len(rows)))
        ax.set_xlim(0, per_row)
        ax.set_ylim(0, len(rows))
        ax.axis("off")
        for r, row in enumerate(rows):
            y = len(rows) - r - 0.5
            for c, label in enumerate(row):
                x = c + 0.5
                _box(ax, x, y, 0.78, 0.5, label, PALETTE[0] if (r * per_row + c) % 2 == 0 else PALETTE[1])
                if c < len(row) - 1:
                    _arrow(ax, x + 0.4, y, x + 0.6, y)
            if r < len(rows) - 1 and len(row) == per_row:  # wrap to next row
                ax.plot([per_row - 0.5, per_row - 0.5, 0.5], [y - 0.25, y - 0.5, y - 0.5],
                        color=PALETTE[4], lw=1.6, zorder=1)
                _arrow(ax, 0.5, y - 0.5, 0.5, y - 0.75)

    ax.set_title(_wrap(title, 60), fontsize=11, fontweight="bold", color=INK, pad=10)
    fig.tight_layout()
    return _to_png(fig)
