import csv
import json
import tempfile
import unittest
from pathlib import Path

from leakagent.benchmark import normalize_benchmark
from leakagent.constants import DETECTOR_FILES
from leakagent.findings import normalize_findings
from leakagent.source_index import build_source_index
from leakagent.text import normalize_method

JAVA_SOURCE = """package demo.app;
public class DemoFragment {
    Object binding;
}
"""

class PipelineTest(unittest.TestCase):
    def test_method_normalization(self):
        self.assertEqual(normalize_method("void lambda$new$1()"), "lambda$new$1")
        self.assertEqual(normalize_method("onCreateView"), "onCreateView")

    def test_index_findings_and_benchmark_linkage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects = root / "projects"; artifact = root / "artifact"
            source = projects / "demo-project" / "app" / "src" / "main" / "java" / "demo" / "app" / "DemoFragment.java"
            source.parent.mkdir(parents=True); source.write_text(JAVA_SOURCE, encoding="utf-8"); artifact.mkdir()
            record = {"project": "demo-project", "text_input": JAVA_SOURCE.replace("\n", "\r\n"), "output": "Yes", "explanation": "Class: demo.app.DemoFragment\nMethod: onCreateView"}
            for filename in DETECTOR_FILES: (artifact / filename).write_text(json.dumps([record] if filename == "FragmentViewFieldRetentionLeak.json" else []), encoding="utf-8")
            db, findings, findings_report = root / "index.sqlite", root / "findings.jsonl", root / "findings-report.json"
            index_result = build_source_index(projects, db); self.assertEqual(index_result["java_files"], 1)
            normalized = normalize_findings(artifact, findings, findings_report, db)
            self.assertEqual(normalized["total_cases"], 1); self.assertEqual(normalized["source_mapping"], {"exact_hash": 1})
            validation = root / "validation.csv"
            with validation.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["ID", "l", "Project", "Class", "Method", "Violation_Details", "Annotator_1_Label", "Notes"]); writer.writeheader()
                writer.writerow({"ID": "1", "l": "FragmentViewFieldLeak", "Project": "demo-project", "Class": "DemoFragment", "Method": "onCreateView", "Violation_Details": "binding retained", "Annotator_1_Label": "TP", "Notes": "confirmed"})
            benchmark, report = root / "gold.jsonl", root / "benchmark-report.json"
            result = normalize_benchmark(validation, findings, benchmark, report)
            self.assertEqual(result["candidate_linkage"], {"exact_detector_project_class_method": 1})
            gold = json.loads(benchmark.read_text(encoding="utf-8")); self.assertEqual(gold["gold_label"], "TP"); self.assertIsNotNone(gold["candidate_id"])

if __name__ == "__main__": unittest.main()
