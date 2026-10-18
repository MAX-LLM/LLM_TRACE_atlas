#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ATLAS = Path(__file__).resolve().parent
ROOT = ATLAS.parent


class AtlasBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ATLAS / "manifest.json").read_text(encoding="utf-8"))
        with (ATLAS / "graph" / "nodes.csv").open(encoding="utf-8", newline="") as handle:
            cls.nodes = list(csv.DictReader(handle))
        with (ATLAS / "graph" / "edges.csv").open(encoding="utf-8", newline="") as handle:
            cls.edges = list(csv.DictReader(handle))

    def test_study_count_matches_frozen_source(self) -> None:
        source = ROOT / self.manifest["source"]
        with source.open(encoding="utf-8-sig", newline="") as handle:
            primary_count = sum(1 for _ in csv.DictReader(handle))
        preprint_source = ROOT / self.manifest["preprint_source"]
        with preprint_source.open(encoding="utf-8-sig", newline="") as handle:
            preprint_count = sum(1 for _ in csv.DictReader(handle))
        self.assertEqual(self.manifest["study_count"], primary_count)
        self.assertEqual(self.manifest["preprint_count"], preprint_count)
        self.assertEqual(self.manifest["total_profile_count"], primary_count + preprint_count)
        self.assertEqual(
            len(list((ATLAS / "wiki" / "studies").glob("REC*.md"))),
            primary_count + preprint_count,
        )

    def test_publication_layers_are_explicit(self) -> None:
        for relative_path, expected_status in [
            (self.manifest["source"], "Peer-reviewed"),
            (self.manifest["preprint_source"], "Preprint"),
        ]:
            with (ROOT / relative_path).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(rows)
            self.assertEqual({row["publication_status"] for row in rows}, {expected_status})

    def test_graph_has_no_dangling_edges(self) -> None:
        node_ids = {row["id"] for row in self.nodes}
        for edge in self.edges:
            self.assertIn(edge["source"], node_ids)
            self.assertIn(edge["target"], node_ids)

    def test_graph_counts_match_manifest(self) -> None:
        self.assertEqual(len(self.nodes), self.manifest["graph_node_count"])
        self.assertEqual(len(self.edges), self.manifest["graph_edge_count"])

    def test_aggregate_graph_is_curated(self) -> None:
        self.assertLess(self.manifest["aggregate_node_count"], 150)

    def test_graphml_is_valid_xml(self) -> None:
        root = ET.parse(ATLAS / "graph" / "knowledge_graph.graphml").getroot()
        self.assertTrue(root.tag.endswith("graphml"))

    def test_static_site_bundle_exists(self) -> None:
        for path in [
            ATLAS / "site" / "index.html",
            ATLAS / "site" / "atlas-data.js",
            ATLAS / "site" / "assets" / "app.js",
            ATLAS / "site" / "assets" / "styles.css",
            ATLAS / "site" / "assets" / "cytoscape.min.js",
        ]:
            self.assertTrue(path.exists(), path)

    def test_static_site_has_optional_evidence_layers(self) -> None:
        index = (ATLAS / "site" / "index.html").read_text(encoding="utf-8")
        app = (ATLAS / "site" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="includePreprints"', index)
        self.assertIn('id="showLowInformation"', index)
        self.assertIn("showLowInformation: false", app)
        self.assertIn('label.startsWith("unclear")', app)
        self.assertIn('label === "none stated"', app)

    def test_supplementary_documentation_exists(self) -> None:
        for name in [
            "entity_dictionary.csv",
            "knowledge_graph_caption.txt",
            "methods_text.txt",
            "figures/figureS2_evidence_atlas_network.pdf",
            "figures/figureS2_evidence_atlas_network.png",
            "figures/figureS3_evidence_pathways.pdf",
            "figures/figureS3_evidence_pathways.png",
        ]:
            self.assertTrue((ATLAS / "supplementary" / name).exists(), name)

    def test_every_study_has_profile_edges(self) -> None:
        study_ids = {row["id"] for row in self.nodes if row["node_type"] == "study"}
        linked_studies = {row["source"] for row in self.edges if row["source"] in study_ids}
        self.assertEqual(linked_studies, study_ids)


if __name__ == "__main__":
    unittest.main()
