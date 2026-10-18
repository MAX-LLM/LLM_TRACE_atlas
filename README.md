# LLM-EHR Evidence Atlas

This repository accompanies **Clinical translation of large language models using
real-world electronic health record data: a systematic review and evidence map**
by Taiyu Zhu and colleagues at King’s College London.

The atlas contains 1,870 peer-reviewed reports and a separate optional layer of
164 eligible preprints. It links study-level classifications to an interactive
evidence map, searchable study browser and research wiki.

- Website: https://max-llm.github.io/LLM_TRACE_atlas/
- Review agent: https://github.com/max-llm/LLM_TRACE
- [Data, build commands and interpretation](evidence_atlas/README.md)
- [Maintenance and release policy](evidence_atlas/MAINTENANCE.md)

## Publish the website

After pushing this repository to GitHub, open **Settings → Pages** and set the
source to **GitHub Actions**. The included workflow deploys
`evidence_atlas/site/` when changes reach `main`. The repository must be public
when using GitHub Free.

## Run locally

```bash
python -m http.server 8000 --directory evidence_atlas/site
```

Open http://localhost:8000/ in a browser. The static site makes no model API calls.

## Check the atlas

```bash
python evidence_atlas/test_atlas.py
```

The public exports contain citation metadata and structured profiles. They do
not contain article full texts, abstracts, raw model responses or credentials.
