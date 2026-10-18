# LLM-EHR Evidence Atlas

The Evidence Atlas compiles the approved evidence-profile library into a
research wiki, a standard knowledge graph, supplementary exports, and an
interactive static explorer. The primary publication-facing source contains
citation metadata and structured evidence fields for 1,870 peer-reviewed
reports. A separate sensitivity layer contains 164 additional eligible
preprints and is hidden by default in the explorer. Both tables omit abstracts,
full text, model rationales, API identifiers, and token accounting.

The atlas version accompanying the manuscript will remain frozen during peer
review; any necessary corrections will be documented and reflected in both.
After publication, we plan quarterly updates, subject to completion of human
review and quality checks, with earlier releases for material corrections.
Each dated release will record the search cutoff and changes to reports,
classifications and methods. The version supporting the published article
will remain archived and separately accessible.

Pushing an updated `site/` bundle to `main` deploys the explorer through the
included GitHub Pages workflow. Repository maintainers should follow
[`MAINTENANCE.md`](MAINTENANCE.md) when preparing a new dated release.

## Build

To refresh a release from private review outcomes, prepare the public Atlas
table by supplying the approved mixed profile and deduplicated citation table:

```bash
python evidence_atlas/prepare_public_data.py \
  --profile /path/to/final_mixed_evidence_profile.csv \
  --records /path/to/deduplicated_database.csv \
  --provenance-results /path/to/dataset_provenance_results.csv \
  --preprint-profile /path/to/preprint_profiles.jsonl
```

Then build the atlas from its approved mixed profile:

```bash
python evidence_atlas/build_atlas.py \
  --run-date 2026-06-01
```

Generate supplementary figures from the same frozen profile table:

```bash
python evidence_atlas/generate_supplementary_figures.py
```

## Generated outputs

- `wiki/`: study, entity, and synthesis pages compatible with Markdown tools.
- `data/`: separate frozen primary and preprint-sensitivity profile tables.
- `graph/`: GraphML, JSON, node CSV, and edge CSV exports.
- `site/atlas-data.js`: the data bundle consumed by the static explorer.
- `supplementary/`: aggregate tables, audit candidates, and figures.
- `manifest.json`: source hash, release date, and output counts.

The frozen public table and generated Atlas are version controlled so the
GitHub Pages site and downloadable graph can be inspected without access to
licensed database exports. Study pages contain citation metadata and structured
profiles, not abstracts or article full text.

The explorer opens on the peer-reviewed primary evidence map. Selecting
`Include preprints` adds the 164 sensitivity-analysis records to the map,
tables, wiki indexes, and CSV exports without changing the primary synthesis
metrics. Low-information graph nodes labelled `Unclear`, `Not reported`,
`No use reported`, or `None stated` are hidden by default and can be restored with the
`Show unclear / not reported` control. This changes only the network display;
it does not remove studies or alter counts, tables, wiki pages, or exports.

## Interpretation

Aggregate graph edges denote study-level co-reporting. For example, a
model-access edge means a model and access category occurred in the same
report; it does not assign that access category intrinsically to every model in
a multi-model study. Classifications derived from titles and abstracts should
not be treated as substitutes for full-text appraisal.

The compilation pattern is adapted from [Karpathy's LLM Wiki
proposal](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
The explorer uses [Cytoscape.js](https://js.cytoscape.org/), with its runtime
and license retained under `site/assets/` for reproducible offline use.
