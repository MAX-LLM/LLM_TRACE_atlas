# Evidence Atlas maintenance

## Source and generated layers

1. `data/evidence_profiles_2026-06-01.csv` is the frozen peer-reviewed source
   for the current release. `data/preprint_sensitivity_profiles_2026-06-01.csv`
   is a separate optional sensitivity layer. Do not edit individual
   classifications in the Atlas.
2. `wiki/`, `graph/`, `site/atlas-data.js`, and `supplementary/` are generated
   outputs. Rebuild them after correcting the private review source and
   preparing a new public table.
3. `build_atlas.py`, the static site source, and this document define how the
   evidence is compiled and displayed.

## Evidence rules

- Preserve the distinction between reported evidence and inferred absence.
- State whether classifications use titles and abstracts or targeted full-text
  review.
- Do not infer dataset access, model access, deployment, or clinical impact
  when the evidence profile records these as unclear.
- Treat consistency flags as audit candidates, not confirmed errors.
- Retain stable `REC` identifiers when rebuilding a release.

## Release workflow

Keep the manuscript's atlas version frozen during peer review. Document any
necessary corrections and apply them consistently to the manuscript and atlas.
After publication, plan quarterly search refreshes and releases, subject to
completion of human adjudication and quality checks. Material corrections may
be released earlier. Archive the version supporting the published article
separately from later updates. Each release must record its search cutoff,
release date, report and classification changes, and any changes to methods,
prompts or model configuration.

1. Complete and freeze the updated private review library.
2. Run `prepare_public_data.py` to create the primary and preprint-sensitivity
   publication-facing tables.
3. Run `build_atlas.py` with the release date.
4. Generate supplementary figures and run `test_atlas.py`.
5. Review new consistency flags and high-impact Level 3, Stage C, and trial
   records before publishing.

## Wiki conventions

- Study pages describe one source record.
- Entity pages aggregate reports sharing one controlled profile label.
- Synthesis pages state cross-study findings and include denominators.
- Cross-links use relative Markdown paths so the wiki works in common Markdown
  tools and GitHub.
