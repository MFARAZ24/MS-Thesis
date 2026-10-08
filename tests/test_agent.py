import json
import tempfile
import unittest
from pathlib import Path

from leakagent.agent.candidates import load_investigation_cases
from leakagent.agent.repo_tools import RepoTools
from leakagent.agent.split import deterministic_split

JAVA_SOURCE = """package demo.app;
public class DemoFragment {
    Object binding;
    void onCreateView() {
        helper.start();
    }
}
"""


class AgentTest(unittest.TestCase):
    def test_deterministic_split_is_stable(self):
        projects = [f"proj-{i:03d}" for i in range(20)]
        dev_a, test_a = deterministic_split(projects, dev_ratio=0.5, seed="s")
        dev_b, test_b = deterministic_split(projects, dev_ratio=0.5, seed="s")
        self.assertEqual(dev_a, dev_b)
        self.assertEqual(test_a, test_b)
        self.assertFalse(set(dev_a) & set(test_a))
        self.assertEqual(len(dev_a) + len(test_a), len(projects))

    def test_load_investigation_cases_joins_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = root / "cases.jsonl"
            gold = root / "gold.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "case_id": "LS-AAA",
                        "detector": "StateHolderLeak",
                        "project": "p1",
                        "class_name": "demo.app.DemoFragment",
                        "simple_class_name": "DemoFragment",
                        "method_name": None,
                        "line_number": None,
                        "package_name": "demo.app",
                        "language": "java",
                        "source_path": "app/DemoFragment.java",
                        "source_hash": "abc",
                        "source_mapping_status": "exact_hash",
                        "raw_explanation": "expl",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            gold.write_text(
                json.dumps(
                    {
                        "benchmark_id": "VAL-001",
                        "candidate_id": "LS-AAA",
                        "detector": "StateHolderLeak",
                        "project": "p1",
                        "class_name": "DemoFragment",
                        "violation_details": "static field",
                        "gold_label": "FP",
                        "review_notes": "benign",
                        "candidate_link_status": "exact_detector_project_class",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            loaded = load_investigation_cases(cases, gold)
            self.assertEqual(len(loaded), 1)
            case = loaded[0]
            self.assertTrue(case.is_gold)
            self.assertEqual(case.gold_label, "FP")
            self.assertEqual(case.detector_recommendation, "primary")

    def test_repo_tools_find_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "projects"
            source = (
                projects
                / "demo-project"
                / "app"
                / "src"
                / "main"
                / "java"
                / "demo"
                / "app"
                / "DemoFragment.java"
            )
            source.parent.mkdir(parents=True)
            source.write_text(JAVA_SOURCE, encoding="utf-8")

            from leakagent.source_index import build_source_index

            db = root / "index.sqlite"
            build_source_index(projects, db)

            tools = RepoTools(db, projects)
            hits = tools.find_symbol("demo-project", "DemoFragment")
            self.assertEqual(len(hits), 1)
            method_hits = tools.find_method("demo-project", "DemoFragment", "onCreateView")
            self.assertTrue(method_hits)
            api_hits = tools.find_api_calls("demo-project", r"helper\.start\(")
            self.assertEqual(len(api_hits), 1)


if __name__ == "__main__":
    unittest.main()