#!/usr/bin/env python3
"""Prepare the publication-facing Evidence Atlas table.

This deterministic export joins citation metadata to the final mixed evidence
profile and removes abstracts, model rationales, API identifiers, and token
accounting before the Atlas is published.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evidence_atlas" / "data" / "evidence_profiles_2026-06-01.csv"
DEFAULT_PREPRINT_OUTPUT = (
    ROOT / "evidence_atlas" / "data" / "preprint_sensitivity_profiles_2026-06-01.csv"
)

PUBLIC_FIELDS = [
    "record_id",
    "title",
    "authors",
    "year",
    "publication_date",
    "journal_or_source",
    "doi",
    "pmid",
    "source_databases",
    "publication_status",
    "dataset_validation_level",
    "clinical_translation_stage",
    "dataset_provenance",
    "model_names",
    "system_or_product_name",
    "model_access_profile",
    "llm_use_mode",
    "named_dataset_or_setting",
    "synthetic_data_use",
    "clinical_specialty",
    "clinical_task",
    "clinical_trial_evidence",
    "human_comparison_or_review",
    "oversight_and_governance",
    "safety_evaluation",
    "outcome_measured",
    "evidence_source",
    "full_text_audit_disposition",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def flatten_profile(profile: dict[str, object]) -> dict[str, str]:
    flat = {key: str(value or "") for key, value in profile.items() if key != "descriptive_fields"}
    fields = profile.get("descriptive_fields") or {}
    if isinstance(fields, dict):
        flat.update({key: str(value or "") for key, value in fields.items()})
    return flat


def write_public_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PUBLIC_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--provenance-results", type=Path)
    parser.add_argument("--preprint-profile", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preprint-output", type=Path, default=DEFAULT_PREPRINT_OUTPUT)
    args = parser.parse_args()

    records = {row.get("record_id", ""): row for row in read_rows(args.records)}
    provenance: dict[str, str] = {}
    if args.provenance_results:
        for row in read_rows(args.provenance_results):
            value = row.get("dataset_provenance", "").strip()
            provenance[row.get("record_id", "").strip()] = (
                value if value and value != "error" else "Unclear"
            )
    public_rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for profile in read_rows(args.profile):
        record_id = profile.get("record_id", "").strip()
        if not record_id or record_id in seen:
            raise ValueError(f"Missing or duplicate record_id: {record_id!r}")
        seen.add(record_id)
        citation = records.get(record_id, {})
        row: dict[str, str] = {}
        for field in PUBLIC_FIELDS:
            row[field] = (profile.get(field) or citation.get(field) or "").strip()
        row["publication_status"] = "Peer-reviewed"
        if provenance:
            row["dataset_provenance"] = provenance.get(record_id, "Unclear")
        public_rows.append(row)

    public_rows.sort(key=lambda row: row["record_id"])
    write_public_rows(args.output, public_rows)
    print(f"Wrote {len(public_rows):,} public Atlas records to {args.output}")

    if args.preprint_profile:
        preprints: list[dict[str, str]] = []
        seen_preprints: set[str] = set()
        for raw_profile in read_jsonl(args.preprint_profile):
            profile = flatten_profile(raw_profile)
            record_id = profile.get("record_id", "").strip()
            if not record_id or record_id in seen_preprints or record_id in seen:
                raise ValueError(f"Missing or duplicate preprint record_id: {record_id!r}")
            seen_preprints.add(record_id)
            citation = records.get(record_id, {})
            row = {
                field: (profile.get(field) or citation.get(field) or "").strip()
                for field in PUBLIC_FIELDS
            }
            row["publication_status"] = "Preprint"
            row["dataset_provenance"] = "Unclear"
            row["evidence_source"] = "title and abstract"
            row["full_text_audit_disposition"] = "preprint sensitivity analysis"
            preprints.append(row)
        preprints.sort(key=lambda row: row["record_id"])
        write_public_rows(args.preprint_output, preprints)
        print(f"Wrote {len(preprints):,} preprint sensitivity records to {args.preprint_output}")


if __name__ == "__main__":
    main()
