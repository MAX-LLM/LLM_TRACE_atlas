#!/usr/bin/env python3
"""Generate supplementary figures from the LLM-EHR Evidence Atlas."""

from __future__ import annotations

import json
import os
import re
import textwrap
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp_matplotlib"))

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.path import Path as MplPath
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch, Rectangle
import pandas as pd


ATLAS = ROOT / "evidence_atlas"
OUTPUT = ATLAS / "supplementary" / "figures"
SOURCE = ATLAS / "data" / "evidence_profiles_2026-06-01.csv"

NPG = {
    "red": "#E64B35",
    "blue": "#4DBBD5",
    "teal": "#00A087",
    "navy": "#3C5488",
    "peach": "#F39B7F",
    "slate": "#8491B4",
    "mint": "#91D1C2",
    "brown": "#7E6148",
    "grey": "#BFC4CB",
    "ink": "#2A2D34",
    "muted": "#6C7480",
}

FIGURE_WIDTH = 7.2

mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "Liberation Sans", "Nimbus Sans", "DejaVu Sans"],
        "font.size": 8.5,
        "axes.labelsize": 8.5,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.dpi": 300,
    }
)


def save_figure(fig: plt.Figure, stem: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUTPUT / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {OUTPUT / stem}")


def load_atlas_data() -> dict[str, object]:
    text = (ATLAS / "site" / "atlas-data.js").read_text(encoding="utf-8")
    prefix = "window.ATLAS_DATA="
    if not text.startswith(prefix):
        raise ValueError("Unexpected atlas data bundle")
    return json.loads(text[len(prefix) :].rstrip(";\n"))


def short_label(label: str) -> str:
    label = re.sub(r"^Level \d:\s*", "", label)
    label = re.sub(r"^Stage [A-C]:\s*", "", label)
    replacements = {
        "Mixed public and private EHR validation": "Public + local validation",
        "Mixed public and local/institutional": "Public + local data",
        "Integrated, interventional, or outcome-impact evaluation": "Integrated / intervention / impact",
        "Prospective or standalone user-facing evaluation": "Prospective / standalone",
        "Retrospective/offline evaluation": "Retrospective / offline",
        "Model accuracy or task performance only": "Task performance",
        "Clinician-created reference labels": "Clinician reference labels",
        "Clinician adjudication or error review": "Clinician review",
        "Direct physician/clinician comparator": "Clinician comparator",
        "Clinician acceptance, edit, or override rate": "Clinician acceptance / edit / override",
        "Patient outcome or experience": "Patient outcome / experience",
        "Both open-weight and proprietary": "Open + proprietary",
        "Closed/proprietary only": "Proprietary only",
    }
    return replacements.get(label, label)


def split_values(value: object) -> list[str]:
    if pd.isna(value) or not str(value).strip():
        return ["Not reported"]
    return [part.strip() for part in str(value).split(";") if part.strip()]


def group_other(value: str, replacement: str) -> str:
    return replacement if value.lower().startswith("other:") else value


def frontier_entities(record: pd.Series) -> dict[str, set[str]]:
    human = {
        f"Human: {group_other(value, 'Other evaluation')}"
        for value in split_values(record["human_comparison_or_review"])
    }
    trial = {
        f"Trial: {group_other(value, 'Other interventional study')}"
        for value in split_values(record["clinical_trial_evidence"])
    }
    outcomes = {group_other(value, "Other reported outcome") for value in split_values(record["outcome_measured"])}
    safety = {
        f"Safety: {group_other(value, 'Other evaluation')}"
        for value in split_values(record["safety_evaluation"])
    }
    oversight = {
        f"Oversight: {group_other(value, 'Other governance')}"
        for value in split_values(record["oversight_and_governance"])
    }
    return {
        "Data and validation": {
            short_label(str(record["dataset_validation_level"])),
            short_label(str(record["dataset_provenance"])),
        },
        "Human and trial evidence": {short_label(value) for value in human | trial},
        "Reported outcomes": {short_label(value) for value in outcomes},
        "Safety and oversight": {short_label(value) for value in safety | oversight},
    }


def even_positions(start: float, stop: float, count: int) -> list[float]:
    if count == 1:
        return [(start + stop) / 2]
    return [start + index * (stop - start) / (count - 1) for index in range(count)]


def evidence_network() -> None:
    studies = pd.read_csv(SOURCE, low_memory=False)
    if "dataset_provenance" not in studies:
        studies["dataset_provenance"] = "Unclear"
    frontier = studies[
        studies["dataset_validation_level"].str.startswith(("Level 2", "Level 3"), na=False)
        & studies["clinical_translation_stage"].str.startswith("Stage C", na=False)
    ].copy()
    if frontier.empty:
        raise ValueError("No Level 2/3 and Stage C reports were found")

    domain_colors = {
        "Data and validation": NPG["navy"],
        "Human and trial evidence": NPG["teal"],
        "Reported outcomes": NPG["blue"],
        "Safety and oversight": NPG["red"],
    }
    report_entities = {
        str(record["record_id"]): frontier_entities(record)
        for _, record in frontier.sort_values("record_id").iterrows()
    }
    entity_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for domains in report_entities.values():
        for domain, entities in domains.items():
            for entity in entities:
                entity_counts[domain][entity] += 1

    entity_positions: dict[tuple[str, str], tuple[float, float]] = {}
    top_entities = sorted(entity_counts["Data and validation"], key=lambda value: (-entity_counts["Data and validation"][value], value))
    right_entities = sorted(entity_counts["Human and trial evidence"], key=lambda value: (-entity_counts["Human and trial evidence"][value], value))
    bottom_entities = sorted(entity_counts["Reported outcomes"], key=lambda value: (-entity_counts["Reported outcomes"][value], value))
    left_entities = sorted(entity_counts["Safety and oversight"], key=lambda value: (-entity_counts["Safety and oversight"][value], value))
    for entity, x in zip(top_entities, even_positions(0.17, 0.83, len(top_entities))):
        entity_positions[("Data and validation", entity)] = (x, 0.88)
    for entity, y in zip(right_entities, even_positions(0.79, 0.21, len(right_entities))):
        entity_positions[("Human and trial evidence", entity)] = (0.91, y)
    for entity, x in zip(bottom_entities, even_positions(0.18, 0.82, len(bottom_entities))):
        entity_positions[("Reported outcomes", entity)] = (x, 0.12)
    for entity, y in zip(left_entities, even_positions(0.76, 0.24, len(left_entities))):
        entity_positions[("Safety and oversight", entity)] = (0.09, y)

    report_positions: dict[str, tuple[float, float]] = {}
    report_ids = sorted(report_entities)
    for index, record_id in enumerate(report_ids):
        column = index % 2
        row = index // 2
        report_positions[record_id] = (0.455 + 0.09 * column, 0.71 - row * 0.07)

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 7.35))
    ax.set_xlim(-0.14, 1.14)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")

    for record_id, domains in report_entities.items():
        start = report_positions[record_id]
        for domain, entities in domains.items():
            for entity in entities:
                end = entity_positions[(domain, entity)]
                midpoint_x = start[0] + (end[0] - start[0]) * 0.55
                path = MplPath(
                    [start, (midpoint_x, start[1]), (midpoint_x, end[1]), end],
                    [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4],
                )
                ax.add_patch(
                    PathPatch(
                        path,
                        facecolor="none",
                        edgecolor=domain_colors[domain],
                        linewidth=0.55,
                        alpha=0.16,
                        zorder=1,
                    )
                )

    for record_id, (x, y) in report_positions.items():
        ax.add_patch(
            FancyBboxPatch(
                (x - 0.039, y - 0.017),
                0.078,
                0.034,
                boxstyle="round,pad=0.003,rounding_size=0.006",
                facecolor="white",
                edgecolor=NPG["ink"],
                linewidth=0.65,
                zorder=4,
            )
        )
        ax.text(x, y, record_id, ha="center", va="center", fontsize=5.4, color=NPG["ink"], zorder=5)

    max_count = max(count for values in entity_counts.values() for count in values.values())
    for (domain, entity), (x, y) in entity_positions.items():
        count = entity_counts[domain][entity]
        radius = 0.008 + 0.014 * (count / max_count) ** 0.5
        ax.add_patch(Circle((x, y), radius, facecolor=domain_colors[domain], edgecolor="white", linewidth=0.65, zorder=4))
        label = f"{short_label(entity)} ({count})"
        if domain == "Data and validation":
            tx, ty, ha, va = x, y + radius + 0.012, "center", "bottom"
            label = "\n".join(textwrap.wrap(label, width=20))
            rotation = 0
        elif domain == "Reported outcomes":
            tx, ty, ha, va = x, y - radius - 0.012, "right", "top"
            label = "\n".join(textwrap.wrap(label, width=22))
            rotation = 48
        elif domain == "Human and trial evidence":
            tx, ty, ha, va = x + radius + 0.012, y, "left", "center"
            label = "\n".join(textwrap.wrap(label, width=27))
            rotation = 0
        else:
            tx, ty, ha, va = x - radius - 0.012, y, "right", "center"
            label = "\n".join(textwrap.wrap(label, width=25))
            rotation = 0
        ax.text(
            tx,
            ty,
            label,
            ha=ha,
            va=va,
            fontsize=5.7,
            color=NPG["ink"],
            linespacing=0.95,
            rotation=rotation,
            rotation_mode="anchor",
        )

    ax.text(
        0.5,
        0.79,
        f"{len(frontier)} reports with Level 2/3 validation\nand Stage C translation",
        ha="center",
        va="center",
        fontsize=7.5,
        fontweight="bold",
        color=NPG["ink"],
    )
    handles = [
        Line2D([0], [0], marker="o", linestyle="none", markersize=6, markerfacecolor=color,
               markeredgecolor="white", label=domain)
        for domain, color in domain_colors.items()
    ]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.085), ncol=4,
              frameon=False, columnspacing=1.0, handletextpad=0.3)
    save_figure(fig, "figureS2_evidence_atlas_network")


def node_positions(counts: pd.Series, gap: float = 0.028) -> dict[str, tuple[float, float]]:
    total = int(counts.sum())
    available = 0.88 - gap * (len(counts) - 1)
    scale = available / total
    positions: dict[str, tuple[float, float]] = {}
    cursor = 0.94
    for label, count in counts.items():
        height = count * scale
        positions[label] = (cursor - height, cursor)
        cursor -= height + gap
    return positions


def draw_ribbon(
    ax: plt.Axes,
    x0: float,
    x1: float,
    source_bounds: tuple[float, float],
    target_bounds: tuple[float, float],
    color: str,
) -> None:
    sy0, sy1 = source_bounds
    ty0, ty1 = target_bounds
    control = (x1 - x0) * 0.44
    vertices = [
        (x0, sy0),
        (x0 + control, sy0),
        (x1 - control, ty0),
        (x1, ty0),
        (x1, ty1),
        (x1 - control, ty1),
        (x0 + control, sy1),
        (x0, sy1),
        (x0, sy0),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.LINETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CLOSEPOLY,
    ]
    ax.add_patch(PathPatch(MplPath(vertices, codes), facecolor=color, edgecolor="none", alpha=0.28))


def draw_flow_layer(
    ax: plt.Axes,
    table: pd.DataFrame,
    source_positions: dict[str, tuple[float, float]],
    target_positions: dict[str, tuple[float, float]],
    x0: float,
    x1: float,
    source_colors: dict[str, str],
) -> None:
    source_offsets = {label: bounds[0] for label, bounds in source_positions.items()}
    target_offsets = {label: bounds[0] for label, bounds in target_positions.items()}
    source_scales = {
        label: (bounds[1] - bounds[0]) / table.loc[label].sum()
        for label, bounds in source_positions.items()
    }
    target_scales = {
        label: (bounds[1] - bounds[0]) / table[label].sum()
        for label, bounds in target_positions.items()
    }
    for source in table.index:
        for target in table.columns:
            count = int(table.loc[source, target])
            if count == 0:
                continue
            source_height = count * source_scales[source]
            target_height = count * target_scales[target]
            source_bounds = (source_offsets[source], source_offsets[source] + source_height)
            target_bounds = (target_offsets[target], target_offsets[target] + target_height)
            draw_ribbon(ax, x0, x1, source_bounds, target_bounds, source_colors[source])
            source_offsets[source] += source_height
            target_offsets[target] += target_height


def evidence_alluvial() -> None:
    studies = pd.read_csv(SOURCE, low_memory=False)
    if "dataset_provenance" not in studies:
        studies["dataset_provenance"] = "Unclear"
    total = len(studies)
    provenance_order = [
        "Public/shareable only",
        "Mixed public and local/institutional",
        "Local/institutional only",
        "Unclear",
    ]
    level_order = [
        "Level 3: Mixed public and private EHR validation",
        "Level 2: Multiple EHR datasets or sites",
        "Level 1: Single EHR dataset validation",
        "Unclear dataset breadth",
    ]
    stage_order = [
        "Stage C: Integrated, interventional, or outcome-impact evaluation",
        "Stage B: Prospective or standalone user-facing evaluation",
        "Stage A: Retrospective/offline evaluation",
        "Unclear translation stage",
    ]

    provenance_counts = studies["dataset_provenance"].value_counts().reindex(provenance_order, fill_value=0)
    level_counts = studies["dataset_validation_level"].value_counts().reindex(level_order, fill_value=0)
    stage_counts = studies["clinical_translation_stage"].value_counts().reindex(stage_order, fill_value=0)
    provenance_counts = provenance_counts[provenance_counts > 0]
    level_counts = level_counts[level_counts > 0]
    stage_counts = stage_counts[stage_counts > 0]
    provenance_order = list(provenance_counts.index)
    level_order = list(level_counts.index)
    stage_order = list(stage_counts.index)
    provenance_to_level = pd.crosstab(
        studies["dataset_provenance"], studies["dataset_validation_level"]
    ).reindex(index=provenance_order, columns=level_order, fill_value=0)
    level_to_stage = pd.crosstab(
        studies["dataset_validation_level"], studies["clinical_translation_stage"]
    ).reindex(index=level_order, columns=stage_order, fill_value=0)

    provenance_positions = node_positions(provenance_counts)
    level_positions = node_positions(level_counts)
    stage_positions = node_positions(stage_counts)
    provenance_colors = dict(
        zip(provenance_order, [NPG["teal"], NPG["blue"], NPG["red"], NPG["slate"]])
    )
    level_colors = dict(
        zip(level_order, [NPG["teal"], NPG["blue"], NPG["navy"], NPG["slate"]])
    )
    stage_colors = dict(
        zip(stage_order, [NPG["teal"], NPG["blue"], NPG["grey"], NPG["slate"]])
    )

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 5.3))
    ax.set_xlim(-0.17, 1.18)
    ax.set_ylim(-0.04, 1.03)
    ax.axis("off")
    x_positions = [0.0, 0.5, 1.0]
    node_width = 0.035
    draw_flow_layer(
        ax,
        provenance_to_level,
        provenance_positions,
        level_positions,
        x_positions[0] + node_width,
        x_positions[1],
        provenance_colors,
    )
    draw_flow_layer(
        ax,
        level_to_stage,
        level_positions,
        stage_positions,
        x_positions[1] + node_width,
        x_positions[2],
        level_colors,
    )

    layers = [
        ("Dataset provenance", provenance_counts, provenance_positions, provenance_colors, x_positions[0], "left"),
        ("Validation breadth", level_counts, level_positions, level_colors, x_positions[1], "center"),
        ("Clinical translation", stage_counts, stage_positions, stage_colors, x_positions[2], "right"),
    ]
    for heading, counts, positions, colors, x, side in layers:
        ax.text(x + node_width / 2, 1.005, heading, ha="center", va="bottom", fontweight="bold", color=NPG["ink"])
        for label, (bottom, top) in positions.items():
            ax.add_patch(Rectangle((x, bottom), node_width, top - bottom, facecolor=colors[label], edgecolor="white", linewidth=0.6))
            count = int(counts[label])
            display = f"{short_label(label)}\n{count:,} ({count / total * 100:.1f}%)"
            if side == "left":
                tx, ha = x - 0.012, "right"
            elif side == "right":
                tx, ha = x + node_width + 0.012, "left"
            else:
                tx, ha = x + node_width / 2, "center"
            ax.text(
                tx,
                (bottom + top) / 2,
                display,
                ha=ha,
                va="center",
                fontsize=6.5,
                color=NPG["ink"],
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 0.4},
            )

    ax.text(0.5, -0.025, f"N = {total:,} reports", ha="center", va="top", fontsize=7.5, color=NPG["muted"])
    save_figure(fig, "figureS3_evidence_pathways")


def main() -> None:
    evidence_network()
    evidence_alluvial()


if __name__ == "__main__":
    main()
