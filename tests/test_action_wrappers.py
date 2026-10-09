import json
import unittest

import test_iterative
from test_iterative import ScriptModel, tool, final
from leakagent.agent.iterative import investigate
from leakagent.agent.model import GenerationResult


class ActionWrapperTest(unittest.TestCase):
    def setUp(self):
        fixture = test_iterative.IterativeTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def run_response(self, raw):
        f = self.fixture
        model = ScriptModel([
            GenerationResult(raw, "script", raw={"done": True}),
            final(["E001"]),
        ])
        return investigate(f.case, f.repo, f.docs, model)

    def test_valid_wrappers_execute_tool(self):
        action = json.dumps(tool(
            "read_source", path="Demo.java", start_line=2, end_line=3
        ))
        wrappers = [
            action,
            "```json\n" + action + "\n```",
            "Explanation.\n\n**Action:** " + action,
            "Explanation.\n\n**Action:**\n```json\n" + action + "\n```",
        ]
        for raw in wrappers:
            with self.subTest(raw=raw):
                decision, evidence, trace = self.run_response(raw)
                self.assertEqual(decision.parse_status, "ok")
                self.assertEqual(len(evidence.code), 1)
                self.assertEqual(trace[0]["raw_response"], raw)

    def test_ambiguous_or_malformed_responses_rejected(self):
        action = json.dumps(tool(
            "read_source", path="Demo.java", start_line=2, end_line=3
        ))
        invalid = [
            "**Action:** " + action + "\n**Action:** " + action,
            "**Action:** " + action + "\nExtra trailing prose.",
            "```json\n" + action,
            "**Action:** " + action + "\n" + action,
            "**Action:** {broken}",
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                decision, evidence, trace = self.run_response(raw)
                self.assertEqual(decision.parse_status, "parse_error")
                self.assertEqual(len(evidence.code), 0)
                self.assertNotIn("tool_request", trace[0])


if __name__ == "__main__":
    unittest.main()
