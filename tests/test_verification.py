
import unittest
from leakagent.agent.decide import Decision, _schema_errors
from leakagent.agent.evidence import EvidenceBundle, CodeEvidence
from leakagent.agent.verify import _verify_citations, verify


class VerificationTest(unittest.TestCase):
    def setUp(self):
        self.evidence = EvidenceBundle(
            case_id="test",
            detector="StateHolderLeak",
            warning_explanation="",
            code=[CodeEvidence(
                path="Example.java",
                line_start=10,
                line_end=12,
                text="void cleanup() {\n  args = null;\n}",
            )],
        )

    def citation_errors(self, path, lines, quote):
        decision = Decision(
            decision="inconclusive",
            confidence=0.2,
            reasoning="Diagnostic.",
            cited_code=[dict(path=path, lines=lines, quote=quote)],
        )
        return _verify_citations(decision, self.evidence)

    def test_valid_source_citation(self):
        self.assertFalse(
            self.citation_errors("Example.java", "11", "args = null;")
        )
        self.assertFalse(self.citation_errors(
            "Example.java", "10-12",
            "void cleanup() {\n  args = null;\n}",
        ))

    def test_invalid_source_citations(self):
        for path, lines, quote in [
            ("Other.java", "11", "args = null;"),
            ("Example.java", "10", "args = null;"),
            ("Example.java", "406-489", "args = null;"),
            ("Example.java", "11", "// invented cleanup"),
            ("Example.java", "12-10", "args = null;"),
        ]:
            with self.subTest(path=path, lines=lines):
                self.assertTrue(self.citation_errors(path, lines, quote))

    def test_conclusive_decisions_require_citations(self):
        for outcome in (
            "confirmed_leak", "likely_leak",
            "properly_released", "false_positive_warning",
        ):
            with self.subTest(outcome=outcome):
                result = verify(Decision(
                    decision=outcome,
                    confidence=0.9,
                    reasoning="Unsupported conclusion.",
                ), self.evidence)
                self.assertTrue(result.overridden)
                self.assertEqual(result.decision.decision, "inconclusive")

    def test_uncited_abstention_is_allowed(self):
        result = verify(Decision(
            decision="inconclusive",
            confidence=0.2,
            reasoning="Insufficient evidence.",
        ), self.evidence)
        self.assertFalse(result.overridden)

    def test_schema_error_status_is_preserved(self):
        result = verify(Decision(
            decision="inconclusive",
            confidence=0,
            reasoning="Invalid schema.",
            parse_status="schema_error",
        ), self.evidence)
        self.assertFalse(result.overridden)
        self.assertEqual(result.decision.parse_status, "schema_error")

    def test_schema_validation(self):
        valid = dict(
            facts=["Evidence is incomplete."],
            decision="inconclusive",
            confidence=0.2,
            reasoning="Transitive references remain unresolved.",
            cited_code=[],
            cited_docs=[],
        )
        self.assertFalse(_schema_errors(valid))
        for confidence in (100, True, float("nan")):
            with self.subTest(confidence=confidence):
                self.assertTrue(_schema_errors(
                    dict(valid, confidence=confidence)
                ))
        self.assertTrue(_schema_errors(
            dict(valid, decision="Consider using View Binding.")
        ))
        self.assertTrue(_schema_errors(dict(
            valid, cited_docs=[dict(doc_id="state-holders", quote="")]
        )))
