#!/usr/bin/env python3
"""Build the LLM-EHR Evidence Atlas from the final profiled study library.

The builder is deliberately deterministic: it compiles the existing structured
profiles into a Markdown wiki, a study-to-entity knowledge graph, supplementary
audit files, and the data bundle consumed by the static atlas interface. It does
not make model calls or modify the source review records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT
    / "evidence_atlas"
    / "data"
    / "evidence_profiles_2026-06-01.csv"
)
DEFAULT_PREPRINT_SOURCE = (
    ROOT
    / "evidence_atlas"
    / "data"
    / "preprint_sensitivity_profiles_2026-06-01.csv"
)
DEFAULT_ATLAS = ROOT / "evidence_atlas"
DISCLAIMER = (
    "The two primary profile labels use titles and abstracts with targeted full-text corrections; "
    "descriptive fields, including trial evidence, use titles and abstracts. "
    "Full texts should be consulted before clinical or policy inference."
)


ENTITY_LABELS = {
    "dataset_validation_level": "Dataset validation",
    "clinical_translation_stage": "Clinical translation",
    "dataset_provenance": "Dataset provenance",
    "model": "Model",
    "model_access": "Model access",
    "llm_use_mode": "LLM use mode",
    "clinical_specialty": "Clinical specialty",
    "public_dataset": "Named public dataset",
    "trial_evidence": "Trial evidence (title/abstract)",
    "human_evidence": "Human evaluation",
    "synthetic_data": "Synthetic data",
    "oversight": "Oversight and governance",
    "safety": "Safety evaluation",
    "outcome": "Outcome",
}

ENTITY_SOURCES = {
    "dataset_validation_level": ("dataset_validation_level", "Single controlled label retained as reported"),
    "clinical_translation_stage": ("clinical_translation_stage", "Single controlled label retained as reported"),
    "dataset_provenance": ("dataset_provenance", "Single controlled label retained as reported"),
    "model": ("model_name_normalized", "Semicolon-delimited normalised model names"),
    "model_access": ("model_access_category", "Grouped as open-weight, proprietary, both, or unclear/other"),
    "llm_use_mode": ("llm_use_mode", "Controlled labels split; free-text Other values grouped for the overview"),
    "clinical_specialty": ("clinical_specialty", "Controlled labels split; free-text Other values grouped for the overview"),
    "public_dataset": ("named_dataset_or_setting", "Named public datasets extracted with documented patterns"),
    "trial_evidence": ("clinical_trial_evidence", "Other interventional descriptions grouped without changing study text"),
    "human_evidence": ("human_comparison_or_review", "Controlled labels split; free-text Other values grouped for the overview"),
    "synthetic_data": ("synthetic_data_use", "Controlled label retained; free-text Other values grouped for the overview"),
    "oversight": ("oversight_and_governance", "Controlled labels split; free-text Other values grouped for the overview"),
    "safety": ("safety_evaluation", "Controlled labels split; free-text Other values grouped for the overview"),
    "outcome": ("outcome_measured", "Controlled labels split; free-text Other values grouped for the overview"),
}

TYPE_COLORS = {
    "dataset_validation_level": "#3C5488",
    "clinical_translation_stage": "#00A087",
    "dataset_provenance": "#E64B35",
    "model": "#4DBBD5",
    "model_access": "#7E6148",
    "llm_use_mode": "#91D1C2",
    "clinical_specialty": "#F39B7F",
    "public_dataset": "#B09C85",
    "trial_evidence": "#DC0000",
    "human_evidence": "#8491B4",
    "synthetic_data": "#6A8E3A",
    "oversight": "#B07AA1",
    "safety": "#D69C2F",
    "outcome": "#557A95",
}

MULTI_FIELDS = {
    "model": "model_names",
    "llm_use_mode": "llm_use_mode",
    "clinical_specialty": "clinical_specialty",
    "human_evidence": "human_comparison_or_review",
    "oversight": "oversight_and_governance",
    "safety": "safety_evaluation",
    "outcome": "outcome_measured",
}

FIXED_FIELDS = {
    "dataset_validation_level": "dataset_validation_level",
    "clinical_translation_stage": "clinical_translation_stage",
    "dataset_provenance": "dataset_provenance",
}

OTHER_BUCKETS = {
    "llm_use_mode": "Other reported LLM use mode",
    "clinical_specialty": "Other specialty",
    "human_evidence": "Other human evaluation",
    "oversight": "Other oversight or governance",
    "safety": "Other safety evaluation",
    "outcome": "Other reported outcome",
}

PUBLIC_DATASET_PATTERNS = [
    ("MIMIC-CXR", (r"\bmimic[- ]?cxr\b",)),
    ("MIMIC-IV", (r"\bmimic[- ]?iv\b",)),
    ("MIMIC-III", (r"\bmimic[- ]?iii\b",)),
    ("MIMIC (unspecified)", (r"\bmimic\b",)),
    ("eICU", (r"\beicu\b",)),
    ("i2b2 / n2c2", (r"\bi2b2\b", r"\bn2c2\b")),
    ("PhysioNet", (r"\bphysionet\b",)),
]

GRAPH_TYPE_LIMITS = {
    "dataset_validation_level": None,
    "clinical_translation_stage": None,
    "dataset_provenance": None,
    "model": 24,
    "model_access": None,
    "llm_use_mode": None,
    "clinical_specialty": 16,
    "public_dataset": None,
    "trial_evidence": None,
    "human_evidence": None,
    "synthetic_data": None,
    "oversight": None,
    "safety": None,
    "outcome": None,
}

GRAPH_PAIRS = [
    ("dataset_provenance", "dataset_validation_level", 1),
    ("dataset_validation_level", "clinical_translation_stage", 1),
    ("clinical_translation_stage", "outcome", 2),
    ("clinical_translation_stage", "safety", 2),
    ("clinical_translation_stage", "human_evidence", 2),
    ("clinical_translation_stage", "trial_evidence", 1),
    ("clinical_translation_stage", "oversight", 1),
    ("model", "llm_use_mode", 4),
    ("model", "clinical_specialty", 4),
    ("model", "model_access", 2),
    ("clinical_specialty", "llm_use_mode", 5),
    ("public_dataset", "dataset_validation_level", 1),
]


@dataclass
class Entity:
    entity_type: str
    label: str
    entity_id: str
    slug: str
    study_ids: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.study_ids)


def clean(value: object, default: str = "Unclear") -> str:
    if value is None:
        return default
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if text and text.lower() not in {"nan", "none"} else default


def split_multi(value: object) -> list[str]:
    text = clean(value, "")
    if not text:
        return []
    return [clean(part) for part in re.split(r"\s*[;|]\s*", text) if clean(part, "")]


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")[:64] or "item"
    suffix = hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]
    return f"{base}-{suffix}"


def entity_id(entity_type: str, label: str) -> str:
    return f"entity:{entity_type}:{slugify(label)}"


def entity_values(row: dict[str, str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for entity_type, column in FIXED_FIELDS.items():
        values[entity_type] = [clean(row.get(column))]

    for entity_type, column in MULTI_FIELDS.items():
        parts = split_multi(row.get(column)) or ["Unclear"]
        bucket = OTHER_BUCKETS.get(entity_type)
        if bucket:
            parts = [bucket if part.lower().startswith("other:") else part for part in parts]
        values[entity_type] = unique(parts)

    access = clean(row.get("model_access_category") or row.get("model_access_profile"))
    lower_access = access.lower()
    has_open = "open-weight" in lower_access
    has_closed = "closed/proprietary" in lower_access
    if has_open and has_closed:
        access_group = "Both open-weight and proprietary"
    elif has_open:
        access_group = "Open-weight only"
    elif has_closed:
        access_group = "Closed/proprietary only"
    else:
        access_group = "Unclear or other"
    values["model_access"] = [access_group]

    trial = clean(row.get("clinical_trial_evidence"), "None stated")
    if trial.startswith("Other interventional study"):
        trial = "Other interventional study"
    values["trial_evidence"] = [trial]

    synthetic = clean(row.get("synthetic_data_use"), "No use reported")
    if synthetic.startswith("Other:"):
        synthetic = "Other reported synthetic-data use"
    values["synthetic_data"] = [synthetic]

    named = clean(row.get("named_dataset_or_setting"), "")
    datasets = []
    for label, patterns in PUBLIC_DATASET_PATTERNS:
        if any(re.search(pattern, named, flags=re.I) for pattern in patterns):
            if label == "MIMIC (unspecified)" and any(item.startswith("MIMIC-") for item in datasets):
                continue
            datasets.append(label)
    values["public_dataset"] = unique(datasets)
    return values


def parse_pmid(value: object) -> str:
    match = re.search(r"\b(\d{7,9})\b", clean(value, ""))
    return match.group(1) if match else ""


def parse_doi(value: object) -> str:
    text = clean(value, "")
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    match = re.search(r"10\.\d{4,9}/[^\s;,]+", text, flags=re.I)
    return match.group(0).rstrip(".)") if match else ""


def source_links(row: dict[str, str]) -> dict[str, str]:
    doi = parse_doi(row.get("doi"))
    pmid = parse_pmid(row.get("pmid"))
    return {
        "doi": doi,
        "doi_url": f"https://doi.org/{doi}" if doi else "",
        "pmid": pmid,
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    }


def load_studies(source: Path, default_publication_status: str) -> list[dict[str, object]]:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    studies: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        record_id = clean(row.get("record_id"), "")
        if not record_id:
            raise ValueError("A profiled row is missing record_id")
        if record_id in seen:
            raise ValueError(f"Duplicate record_id in profile library: {record_id}")
        seen.add(record_id)
        links = source_links(row)
        row_entities = entity_values(row)
        try:
            report_year = int(float(clean(row.get("report_year"), clean(row.get("year"), "0"))))
        except ValueError:
            report_year = 0
        study = {
            "id": record_id,
            "title": clean(row.get("title"), "Untitled record"),
            "authors": clean(row.get("authors"), "Not reported"),
            "year": report_year,
            "publication_date": clean(row.get("publication_date"), "Unclear"),
            "journal": clean(row.get("journal_or_source"), "Unclear"),
            "source_databases": clean(row.get("source_databases"), clean(row.get("database_source"))),
            "publication_status": clean(row.get("publication_status"), default_publication_status),
            "doi": links["doi"],
            "doi_url": links["doi_url"],
            "pmid": links["pmid"],
            "pubmed_url": links["pubmed_url"],
            "dataset_validation_level": clean(row.get("dataset_validation_level")),
            "clinical_translation_stage": clean(row.get("clinical_translation_stage")),
            "dataset_provenance": clean(row.get("dataset_provenance")),
            "model_names": clean(row.get("model_names")),
            "model_names_normalized": split_multi(
                row.get("model_name_normalized") or row.get("model_names")
            ) or ["Unclear"],
            "model_access": clean(
                row.get("model_access_category") or row.get("model_access_profile")
            ),
            "model_access_group": row_entities["model_access"][0],
            "llm_use_mode": split_multi(row.get("llm_use_mode")) or ["Unclear"],
            "named_dataset_or_setting": clean(row.get("named_dataset_or_setting")),
            "clinical_specialty": split_multi(row.get("clinical_specialty")) or ["Unclear"],
            "clinical_task": clean(row.get("clinical_task")),
            "trial_evidence": clean(row.get("clinical_trial_evidence"), "None stated"),
            "human_evidence": split_multi(row.get("human_comparison_or_review")) or ["Not reported"],
            "synthetic_data": clean(row.get("synthetic_data_use"), "No use reported"),
            "oversight": split_multi(row.get("oversight_and_governance")) or ["Not reported"],
            "safety": split_multi(row.get("safety_evaluation")) or ["Not reported"],
            "outcomes": split_multi(row.get("outcome_measured")) or ["Not reported"],
            "rationale": clean(row.get("rationale"), "Not reported"),
            "profile_provider": clean(row.get("profile_provider") or row.get("provider")),
            "profile_model": clean(row.get("profile_model") or row.get("model")),
            "entities": row_entities,
        }
        studies.append(study)

    studies.sort(key=lambda item: (item["id"]))
    return studies


def build_entities(studies: list[dict[str, object]]) -> dict[tuple[str, str], Entity]:
    entities: dict[tuple[str, str], Entity] = {}
    for study in studies:
        for entity_type, labels in study["entities"].items():
            for label in labels:
                key = (entity_type, label)
                if key not in entities:
                    slug = slugify(label)
                    entities[key] = Entity(entity_type, label, entity_id(entity_type, label), slug)
                entities[key].study_ids.append(str(study["id"]))
    for entity in entities.values():
        entity.study_ids.sort()
    return entities


def distribution(studies_by_id: dict[str, dict[str, object]], study_ids: list[str], field: str) -> dict[str, int]:
    counts = Counter(str(studies_by_id[study_id][field]) for study_id in study_ids)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def select_graph_entities(entities: dict[tuple[str, str], Entity]) -> dict[str, Entity]:
    selected: dict[str, Entity] = {}
    by_type: dict[str, list[Entity]] = defaultdict(list)
    for entity in entities.values():
        by_type[entity.entity_type].append(entity)
    for entity_type, items in by_type.items():
        items.sort(key=lambda entity: (-entity.count, entity.label))
        limit = GRAPH_TYPE_LIMITS.get(entity_type)
        if entity_type in {"model", "clinical_specialty"}:
            items = [item for item in items if item.label not in {"Unclear", "Other specialty"}]
        for entity in items if limit is None else items[:limit]:
            selected[entity.entity_id] = entity
    return selected


def build_aggregate_graph(
    studies: list[dict[str, object]], selected: dict[str, Entity]
) -> dict[str, list[dict[str, object]]]:
    selected_ids = set(selected)
    edge_studies: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for study in studies:
        entities = study["entities"]
        for left_type, right_type, minimum in GRAPH_PAIRS:
            for left_label in entities.get(left_type, []):
                left = entity_id(left_type, left_label)
                if left not in selected_ids:
                    continue
                for right_label in entities.get(right_type, []):
                    right = entity_id(right_type, right_label)
                    if right not in selected_ids or left == right:
                        continue
                    edge_studies[(left, right, f"{left_type}_to_{right_type}")].append(str(study["id"]))

    nodes = [
        {
            "id": entity.entity_id,
            "label": entity.label,
            "type": entity.entity_type,
            "type_label": ENTITY_LABELS[entity.entity_type],
            "count": entity.count,
            "color": TYPE_COLORS[entity.entity_type],
            "study_ids": entity.study_ids,
        }
        for entity in selected.values()
    ]
    nodes.sort(key=lambda node: (node["type"], -int(node["count"]), node["label"]))

    pair_minimum = {(left, right): minimum for left, right, minimum in GRAPH_PAIRS}
    edges = []
    for (source, target, relation), study_ids in edge_studies.items():
        source_type = selected[source].entity_type
        target_type = selected[target].entity_type
        if len(study_ids) < pair_minimum[(source_type, target_type)]:
            continue
        edges.append(
            {
                "id": f"edge:{source}:{target}",
                "source": source,
                "target": target,
                "relation": relation,
                "weight": len(study_ids),
                "study_ids": sorted(study_ids),
            }
        )
    edges.sort(key=lambda edge: (edge["relation"], edge["source"], edge["target"]))
    return {"nodes": nodes, "edges": edges}


def markdown_link(text: str, target: str) -> str:
    return f"[{text.replace('[', '').replace(']', '')}]({target})"


def yaml_quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def study_page(study: dict[str, object], entities: dict[tuple[str, str], Entity]) -> str:
    entity_lines = []
    for entity_type in ENTITY_LABELS:
        links = []
        for label in study["entities"].get(entity_type, []):
            entity = entities[(entity_type, label)]
            links.append(markdown_link(label, f"../entities/{entity_type}/{entity.slug}.md"))
        if links:
            entity_lines.append(f"| {ENTITY_LABELS[entity_type]} | {'; '.join(links)} |")

    source_parts = []
    if study["doi_url"]:
        source_parts.append(markdown_link(f"DOI {study['doi']}", str(study["doi_url"])))
    if study["pubmed_url"]:
        source_parts.append(markdown_link(f"PubMed {study['pmid']}", str(study["pubmed_url"])))
    source_text = " | ".join(source_parts) if source_parts else "No DOI or PubMed identifier available"
    return "\n".join(
        [
            "---",
            f"record_id: {yaml_quote(study['id'])}",
            f"title: {yaml_quote(study['title'])}",
            f"year: {study['year']}",
            f"journal: {yaml_quote(study['journal'])}",
            "page_type: study",
            "---",
            "",
            f"# {study['title']}",
            "",
            f"**Record:** {study['id']}",
            "",
            f"**Publication status:** {study['publication_status']}",
            "",
            f"**Citation metadata:** {study['authors']} ({study['year']}). {study['journal']}",
            "",
            f"**Source:** {source_text}",
            "",
            "## Evidence profile",
            "",
            "| Dimension | Classification |",
            "|---|---|",
            *entity_lines,
            "",
            "## Clinical task",
            "",
            str(study["clinical_task"]),
            "",
            "## Named dataset or setting",
            "",
            str(study["named_dataset_or_setting"]),
            "",
            "## Profile rationale",
            "",
            str(study["rationale"]),
            "",
            "---",
            DISCLAIMER,
            "",
        ]
    )


def entity_page(
    entity: Entity, studies_by_id: dict[str, dict[str, object]]
) -> str:
    years = distribution(studies_by_id, entity.study_ids, "year")
    levels = distribution(studies_by_id, entity.study_ids, "dataset_validation_level")
    stages = distribution(studies_by_id, entity.study_ids, "clinical_translation_stage")
    rows = []
    for study_id in sorted(entity.study_ids, key=lambda item: (-int(studies_by_id[item]["year"]), item)):
        study = studies_by_id[study_id]
        rows.append(
            f"- {markdown_link(str(study['title']), f'../../studies/{study_id}.md')} "
            f"({study['year']}; {study_id})"
        )

    def table(data: dict[str, int]) -> list[str]:
        result = ["| Classification | Reports |", "|---|---:|"]
        result.extend(f"| {label} | {count:,} |" for label, count in data.items())
        return result

    return "\n".join(
        [
            "---",
            f"title: {yaml_quote(entity.label)}",
            f"entity_type: {yaml_quote(entity.entity_type)}",
            f"report_count: {entity.count}",
            "page_type: entity",
            "---",
            "",
            f"# {entity.label}",
            "",
            f"**Entity type:** {ENTITY_LABELS[entity.entity_type]}",
            "",
            f"**Linked reports:** {entity.count:,}",
            "",
            "## Publication years",
            "",
            *table(years),
            "",
            "## Dataset validation",
            "",
            *table(levels),
            "",
            "## Clinical translation",
            "",
            *table(stages),
            "",
            "## Linked studies",
            "",
            *rows,
            "",
            "---",
            DISCLAIMER,
            "",
        ]
    )


def count_contains(studies: list[dict[str, object]], field: str, label: str) -> int:
    return sum(label in study[field] for study in studies)


def synthesis_metrics(studies: list[dict[str, object]]) -> dict[str, int]:
    return {
        "total": len(studies),
        "from_2024": sum(int(study["year"]) >= 2024 for study in studies),
        "level_1": sum(str(study["dataset_validation_level"]).startswith("Level 1") for study in studies),
        "stage_a": sum(str(study["clinical_translation_stage"]).startswith("Stage A") for study in studies),
        "stage_b_or_c": sum(
            str(study["clinical_translation_stage"]).startswith(("Stage B", "Stage C")) for study in studies
        ),
        "broader_stage_c": sum(
            str(study["dataset_validation_level"]).startswith(("Level 2", "Level 3"))
            and str(study["clinical_translation_stage"]).startswith("Stage C")
            for study in studies
        ),
        "mixed_stage_c": sum(
            str(study["dataset_validation_level"]).startswith("Level 3")
            and str(study["clinical_translation_stage"]).startswith("Stage C")
            for study in studies
        ),
        "local_only": sum(study["dataset_provenance"] == "Local/institutional only" for study in studies),
        "provenance_unclear": sum(study["dataset_provenance"] == "Unclear" for study in studies),
        "patient_outcome": count_contains(studies, "outcomes", "Patient outcome or experience"),
        "task_performance": count_contains(studies, "outcomes", "Model accuracy or task performance only"),
        "governance_unreported": count_contains(studies, "oversight", "Not reported"),
        "safety_unreported": count_contains(studies, "safety", "Not reported"),
    }


def synthesis_pages(metrics: dict[str, int]) -> dict[str, str]:
    total = metrics["total"]

    def pct(value: int) -> str:
        return f"{value / total * 100:.1f}%"

    overview = f"""# Field overview

The atlas contains **{total:,} included reports** published from 2022 to June 1, 2026. Of these, **{metrics['from_2024']:,} ({pct(metrics['from_2024'])})** were published from 2024 onwards. The evidence base is therefore recent and expanding rapidly.

Evidence maturity has not increased at the same rate as publication volume. **{metrics['level_1']:,} ({pct(metrics['level_1'])})** reports evaluated one EHR dataset, cohort, institution, or health system, and **{metrics['stage_a']:,} ({pct(metrics['stage_a'])})** were retrospective or offline. Only **{metrics['stage_b_or_c']:,} ({pct(metrics['stage_b_or_c'])})** reported prospective, user-facing, integrated, interventional, or outcome-impact evaluation.

## Core synthesis

- [[clinical-translation-gap|Clinical translation gap]]
- [[dataset-transportability|Dataset transportability]]
- [[outcomes-safety-governance|Outcomes, safety, and governance]]
- [[model-ecosystem|Model ecosystem]]

---
{DISCLAIMER}
"""
    translation = f"""# Clinical translation gap

The main evidence gap is the limited intersection between broader validation and evaluation in clinical use. Only **{metrics['broader_stage_c']:,} reports ({pct(metrics['broader_stage_c'])})** combined Level 2 or Level 3 validation with Stage C evidence. Only **{metrics['mixed_stage_c']:,} ({pct(metrics['mixed_stage_c'])})** combined mixed public and local validation with Stage C evidence.

These dimensions should remain separate. Multi-dataset retrospective validation informs transportability, whereas integrated or interventional evaluation informs clinical use. Neither dimension can substitute for the other.

---
{DISCLAIMER}
"""
    transport = f"""# Dataset transportability

At least **{metrics['local_only']:,} reports ({pct(metrics['local_only'])})** used only local or institutional EHR data. Dataset provenance was unclear in a further **{metrics['provenance_unclear']:,} ({pct(metrics['provenance_unclear'])})**.

Local data provide clinical realism but do not, without independently sourced evaluation, establish transportability across documentation systems, patient populations, languages, or health systems. Public datasets improve reproducibility but can also concentrate evidence within a small number of institutions.

---
{DISCLAIMER}
"""
    outcomes = f"""# Outcomes, safety, and governance

Model accuracy or task performance was reported in **{metrics['task_performance']:,} reports ({pct(metrics['task_performance'])})**, whereas patient outcomes or experience were reported in **{metrics['patient_outcome']:,} ({pct(metrics['patient_outcome'])})**. Oversight or governance was not described in **{metrics['governance_unreported']:,} ({pct(metrics['governance_unreported'])})**, and safety evaluation was not described in **{metrics['safety_unreported']:,} ({pct(metrics['safety_unreported'])})**.

Absence from a title or abstract does not establish absence from the study. These fields identify reporting gaps and candidates for targeted full-text review.

---
{DISCLAIMER}
"""
    models = f"""# Model ecosystem

The model graph links named model families to access categories, use modes, specialties, and translation stages. Edges indicate study-level co-reporting: a model and an access category appeared in the same report. They do not assign that access category intrinsically to every model in a multi-model report. The graph is intended to support comparisons of where open-weight and proprietary models are evaluated and whether model families are represented beyond retrospective task-performance studies.

Model-name and access categories were normalised after profiling. Ambiguous names and access routes remain explicitly labelled as unclear rather than inferred.

---
{DISCLAIMER}
"""
    return {
        "field-overview.md": overview,
        "clinical-translation-gap.md": translation,
        "dataset-transportability.md": transport,
        "outcomes-safety-governance.md": outcomes,
        "model-ecosystem.md": models,
    }


def audit_candidates(studies: list[dict[str, object]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for study in studies:
        reasons = []
        if str(study["dataset_validation_level"]).startswith("Level 3") and study["dataset_provenance"] != "Mixed public and local/institutional":
            reasons.append("Level 3 classification without mixed provenance label")
        if study["dataset_provenance"] == "Mixed public and local/institutional" and not str(study["dataset_validation_level"]).startswith("Level 3"):
            reasons.append("Mixed provenance label without Level 3 classification")
        if study["trial_evidence"] in {"Randomized clinical trial", "Single-arm pilot implementation"} and str(study["clinical_translation_stage"]).startswith("Stage A"):
            reasons.append("Trial or pilot label with retrospective/offline translation stage")
        named = str(study["named_dataset_or_setting"])
        mentions_public = any(any(re.search(pattern, named, flags=re.I) for pattern in patterns) for _, patterns in PUBLIC_DATASET_PATTERNS)
        if mentions_public and study["dataset_provenance"] == "Local/institutional only":
            reasons.append("Named public dataset with local-only provenance label")
        for reason in reasons:
            rows.append(
                {
                    "record_id": str(study["id"]),
                    "title": str(study["title"]),
                    "audit_reason": reason,
                    "dataset_validation_level": str(study["dataset_validation_level"]),
                    "clinical_translation_stage": str(study["clinical_translation_stage"]),
                    "dataset_provenance": str(study["dataset_provenance"]),
                    "named_dataset_or_setting": str(study["named_dataset_or_setting"]),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_graph_exports(
    graph_dir: Path,
    studies: list[dict[str, object]],
    entities: dict[tuple[str, str], Entity],
) -> tuple[int, int]:
    graph_dir.mkdir(parents=True, exist_ok=True)
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    for study in studies:
        nodes.append(
            {
                "id": f"study:{study['id']}",
                "node_type": "study",
                "label": study["title"],
                "record_id": study["id"],
                "year": study["year"],
                "count": "",
            }
        )
        for entity_type, labels in study["entities"].items():
            for label in labels:
                entity = entities[(entity_type, label)]
                edges.append(
                    {
                        "source": f"study:{study['id']}",
                        "target": entity.entity_id,
                        "relation": f"has_{entity_type}",
                        "weight": 1,
                    }
                )
    for entity in entities.values():
        nodes.append(
            {
                "id": entity.entity_id,
                "node_type": entity.entity_type,
                "label": entity.label,
                "record_id": "",
                "year": "",
                "count": entity.count,
            }
        )
    nodes.sort(key=lambda row: str(row["id"]))
    edges.sort(key=lambda row: (str(row["source"]), str(row["target"])))
    write_csv(graph_dir / "nodes.csv", nodes, ["id", "node_type", "label", "record_id", "year", "count"])
    write_csv(graph_dir / "edges.csv", edges, ["source", "target", "relation", "weight"])
    (graph_dir / "knowledge_graph.json").write_text(
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    namespace = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}graphml")
    keys = [
        ("label", "node", "string"),
        ("node_type", "node", "string"),
        ("record_id", "node", "string"),
        ("year", "node", "string"),
        ("count", "node", "string"),
        ("relation", "edge", "string"),
        ("weight", "edge", "double"),
    ]
    for key_id, target, value_type in keys:
        ET.SubElement(root, f"{{{namespace}}}key", id=key_id, **{"for": target, "attr.name": key_id, "attr.type": value_type})
    graph = ET.SubElement(root, f"{{{namespace}}}graph", id="LLM_EHR_Evidence_Atlas", edgedefault="directed")
    for row in nodes:
        node = ET.SubElement(graph, f"{{{namespace}}}node", id=str(row["id"]))
        for field_name in ["label", "node_type", "record_id", "year", "count"]:
            data = ET.SubElement(node, f"{{{namespace}}}data", key=field_name)
            data.text = str(row[field_name])
    for index, row in enumerate(edges, start=1):
        edge = ET.SubElement(graph, f"{{{namespace}}}edge", id=f"e{index}", source=str(row["source"]), target=str(row["target"]))
        relation = ET.SubElement(edge, f"{{{namespace}}}data", key="relation")
        relation.text = str(row["relation"])
        weight = ET.SubElement(edge, f"{{{namespace}}}data", key="weight")
        weight.text = str(row["weight"])
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(graph_dir / "knowledge_graph.graphml", encoding="utf-8", xml_declaration=True)
    return len(nodes), len(edges)


def write_wiki(
    wiki_dir: Path,
    studies: list[dict[str, object]],
    entities: dict[tuple[str, str], Entity],
    metrics: dict[str, int],
    run_date: str,
    primary_count: int,
    preprint_count: int,
) -> None:
    studies_dir = wiki_dir / "studies"
    entities_dir = wiki_dir / "entities"
    synthesis_dir = wiki_dir / "synthesis"
    studies_dir.mkdir(parents=True, exist_ok=True)
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    for entity_type in ENTITY_LABELS:
        (entities_dir / entity_type).mkdir(parents=True, exist_ok=True)

    studies_by_id = {str(study["id"]): study for study in studies}
    for study in studies:
        (studies_dir / f"{study['id']}.md").write_text(study_page(study, entities), encoding="utf-8")
    for entity in entities.values():
        path = entities_dir / entity.entity_type / f"{entity.slug}.md"
        path.write_text(entity_page(entity, studies_by_id), encoding="utf-8")
    for filename, content in synthesis_pages(metrics).items():
        (synthesis_dir / filename).write_text(content, encoding="utf-8")

    by_type: dict[str, list[Entity]] = defaultdict(list)
    for entity in entities.values():
        by_type[entity.entity_type].append(entity)
    index_lines = [
        "# LLM-EHR Evidence Atlas",
        "",
        f"**Primary peer-reviewed reports:** {primary_count:,}",
        "",
        f"**Additional eligible preprints:** {preprint_count:,}",
        "",
        "**Publication window:** Jan 1, 2022 to June 1, 2026",
        "",
        "**Source:** final profiled review library",
        "",
        "## Synthesis",
        "",
        "- [Field overview](synthesis/field-overview.md)",
        "- [Clinical translation gap](synthesis/clinical-translation-gap.md)",
        "- [Dataset transportability](synthesis/dataset-transportability.md)",
        "- [Outcomes, safety, and governance](synthesis/outcomes-safety-governance.md)",
        "- [Model ecosystem](synthesis/model-ecosystem.md)",
        "",
        "## Entity indexes",
        "",
    ]
    for entity_type in ENTITY_LABELS:
        items = sorted(by_type[entity_type], key=lambda item: (-item.count, item.label))
        index_lines.append(f"### {ENTITY_LABELS[entity_type]}")
        index_lines.append("")
        for entity in items:
            index_lines.append(
                f"- {markdown_link(entity.label, f'entities/{entity_type}/{entity.slug}.md')} ({entity.count:,})"
            )
        index_lines.append("")
    index_lines.extend(["---", DISCLAIMER, ""])
    (wiki_dir / "index.md").write_text("\n".join(index_lines), encoding="utf-8")
    (wiki_dir / "log.md").write_text(
        f"# Atlas log\n\n## [{run_date}] build | Compiled {primary_count:,} primary reports and {preprint_count:,} preprints\n\n"
        "Generated study pages, entity pages, synthesis pages, graph exports, and the static atlas data bundle.\n",
        encoding="utf-8",
    )


def compact_study(study: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in study.items() if key != "entities"}


def write_site_data(
    site_dir: Path,
    studies: list[dict[str, object]],
    entities: dict[tuple[str, str], Entity],
    aggregate_graph: dict[str, list[dict[str, object]]],
    metrics: dict[str, int],
    primary_count: int,
    preprint_count: int,
) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    all_entities = [
        {
            "id": entity.entity_id,
            "label": entity.label,
            "type": entity.entity_type,
            "type_label": ENTITY_LABELS[entity.entity_type],
            "count": entity.count,
            "color": TYPE_COLORS[entity.entity_type],
            "study_ids": entity.study_ids,
        }
        for entity in entities.values()
    ]
    all_entities.sort(key=lambda item: (item["type"], -int(item["count"]), item["label"]))
    payload = {
        "meta": {
            "title": "LLM-EHR Evidence Atlas",
            "study_count": primary_count,
            "preprint_count": preprint_count,
            "total_with_preprints": primary_count + preprint_count,
            "publication_window": "Jan 1, 2022 to June 1, 2026",
            "cutoff_date": "2026-06-01",
            "disclaimer": DISCLAIMER,
        },
        "metrics": metrics,
        "studies": [compact_study(study) for study in studies],
        "entities": all_entities,
        "graph": aggregate_graph,
        "type_labels": ENTITY_LABELS,
        "type_colors": TYPE_COLORS,
    }
    (site_dir / "atlas-data.js").write_text(
        "window.ATLAS_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


def write_supplementary(
    supplementary_dir: Path,
    entities: dict[tuple[str, str], Entity],
    audits: list[dict[str, str]],
    node_count: int,
    edge_count: int,
) -> None:
    supplementary_dir.mkdir(parents=True, exist_ok=True)
    entity_rows = [
        {
            "entity_type": entity.entity_type,
            "entity_type_label": ENTITY_LABELS[entity.entity_type],
            "entity": entity.label,
            "report_count": entity.count,
        }
        for entity in entities.values()
    ]
    entity_rows.sort(key=lambda row: (row["entity_type"], -int(row["report_count"]), row["entity"]))
    write_csv(
        supplementary_dir / "entity_counts.csv",
        entity_rows,
        ["entity_type", "entity_type_label", "entity", "report_count"],
    )
    write_csv(
        supplementary_dir / "audit_candidates.csv",
        audits,
        [
            "record_id",
            "title",
            "audit_reason",
            "dataset_validation_level",
            "clinical_translation_stage",
            "dataset_provenance",
            "named_dataset_or_setting",
        ],
    )
    dictionary_rows = [
        {
            "entity_type": entity_type,
            "display_label": ENTITY_LABELS[entity_type],
            "source_profile_field": ENTITY_SOURCES[entity_type][0],
            "compilation_rule": ENTITY_SOURCES[entity_type][1],
        }
        for entity_type in ENTITY_LABELS
    ]
    write_csv(
        supplementary_dir / "entity_dictionary.csv",
        dictionary_rows,
        ["entity_type", "display_label", "source_profile_field", "compilation_rule"],
    )
    caption = (
        "Supplementary figure: Interactive evidence knowledge graph for large language model studies using "
        "electronic health records. Nodes represent structured evidence entities, including dataset-validation "
        "levels, clinical-translation stages, dataset provenance, model families, use modes, clinical specialties, "
        "trial and human evidence, safety evaluations, governance, and outcomes. Edges indicate that entities were "
        "reported in the same included study, and edge width represents the number of linked reports. A model--access "
        "edge therefore denotes co-reporting and does not assign that access category intrinsically to every model in "
        "a multi-model report. Filters permit "
        "exploration by publication year and the two primary evidence dimensions. The downloadable bipartite graph "
        f"contains {node_count:,} study and entity nodes and {edge_count:,} study-to-entity edges. Classifications are "
        "based on titles, abstracts, and bibliographic metadata."
    )
    (supplementary_dir / "knowledge_graph_caption.txt").write_text(caption + "\n", encoding="utf-8")
    methods = (
        "After screening and evidence profiling were complete, we compiled the structured study records into a "
        "deterministic evidence atlas without additional model inference. Each included report was represented as a "
        "study node and linked to controlled entity nodes for dataset validation, clinical translation, dataset "
        "provenance, models, model access, use modes, specialties, named public datasets, human and trial evidence, "
        "synthetic-data use, safety, oversight, and outcomes. The interactive overview displays selected entity-to-entity "
        "co-occurrences aggregated through shared study records; these edges denote co-reporting rather than causal or "
        "semantic relations. Stable record identifiers connect every aggregate count to a study page, and CSV, JSON, and "
        "GraphML exports preserve the complete study-to-entity graph for independent analysis. Free-text Other responses "
        "were grouped only in the overview, while their original study-level text was retained."
    )
    (supplementary_dir / "methods_text.txt").write_text(methods + "\n", encoding="utf-8")
    (supplementary_dir / "README.md").write_text(
        "# Supplementary atlas exports\n\n"
        "- `entity_counts.csv`: report counts for every canonical graph entity.\n"
        "- `entity_dictionary.csv`: source fields and deterministic compilation rules for each entity type.\n"
        "- `audit_candidates.csv`: deterministic consistency checks for targeted full-text review; flags are not confirmed errors.\n"
        "- `knowledge_graph_caption.txt`: draft caption for the interactive graph or a supplementary figure.\n"
        "- `methods_text.txt`: draft supplementary methods description.\n\n"
        f"{DISCLAIMER}\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--preprint-source", type=Path, default=DEFAULT_PREPRINT_SOURCE)
    parser.add_argument("--atlas-dir", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--run-date", default=date.today().isoformat())
    args = parser.parse_args()

    source = args.source.resolve()
    preprint_source = args.preprint_source.resolve()
    atlas_dir = args.atlas_dir.resolve()
    primary_studies = load_studies(source, "Peer-reviewed")
    preprint_studies = load_studies(preprint_source, "Preprint") if preprint_source.exists() else []
    studies = primary_studies + preprint_studies
    study_ids = [str(study["id"]) for study in studies]
    if len(study_ids) != len(set(study_ids)):
        raise ValueError("Primary and preprint Atlas sources contain duplicate record IDs")
    studies.sort(key=lambda item: str(item["id"]))
    entities = build_entities(studies)
    selected = select_graph_entities(entities)
    aggregate_graph = build_aggregate_graph(studies, selected)
    metrics = synthesis_metrics(primary_studies)
    audits = audit_candidates(primary_studies)

    for generated_dir in [atlas_dir / "wiki", atlas_dir / "graph"]:
        if generated_dir.exists():
            shutil.rmtree(generated_dir)

    write_wiki(
        atlas_dir / "wiki",
        studies,
        entities,
        metrics,
        args.run_date,
        len(primary_studies),
        len(preprint_studies),
    )
    node_count, edge_count = write_graph_exports(atlas_dir / "graph", studies, entities)
    write_site_data(
        atlas_dir / "site",
        studies,
        entities,
        aggregate_graph,
        metrics,
        len(primary_studies),
        len(preprint_studies),
    )
    write_supplementary(atlas_dir / "supplementary", entities, audits, node_count, edge_count)

    manifest = {
        "atlas_version": "1.0",
        "run_date": args.run_date,
        "source": str(source.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "preprint_source": str(preprint_source.relative_to(ROOT)) if preprint_studies else None,
        "preprint_source_sha256": hashlib.sha256(preprint_source.read_bytes()).hexdigest() if preprint_studies else None,
        "study_count": len(primary_studies),
        "preprint_count": len(preprint_studies),
        "total_profile_count": len(studies),
        "entity_count": len(entities),
        "graph_node_count": node_count,
        "graph_edge_count": edge_count,
        "aggregate_node_count": len(aggregate_graph["nodes"]),
        "aggregate_edge_count": len(aggregate_graph["edges"]),
        "audit_candidate_count": len(audits),
    }
    (atlas_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"Built atlas: {len(primary_studies):,} primary studies + {len(preprint_studies):,} preprints, "
        f"{len(entities):,} entities, "
        f"{node_count:,} graph nodes, {edge_count:,} graph edges"
    )


if __name__ == "__main__":
    main()
