import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from leakagent.agent.iterative import investigate, ToolSession
from leakagent.agent.model import GenerationResult, OllamaModel
from leakagent.agent.repo_tools import RepoTools
from leakagent.docs.bm25 import BM25, Doc
from leakagent.source_index import build_source_index


class ScriptModel:
    name = 'script'
    def __init__(self, actions):
        self.actions = iter(actions)
        self.prompts = []
    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        item = next(self.actions)
        if isinstance(item, GenerationResult):
            return item
        return GenerationResult(json.dumps(item), self.name, raw={'done': True})


def tool(tool_name, **args):
    return {'action': 'tool', 'tool': tool_name, 'arguments': args}


def final(ids=None):
    return {'action': 'final', 'decision': 'likely_leak', 'confidence': .7,
            'reasoning': 'The cited field retains a reference.', 'evidence_ids': ids or []}


class IterativeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.projects = root/'projects'
        source = self.projects/'p'/'Demo.java'
        source.parent.mkdir(parents=True)
        source.write_text('package demo;\nclass Demo {\n Object retained;\n}\n')
        other = self.projects/'other'/'Secret.java'
        other.parent.mkdir()
        other.write_text('class Secret {}')
        db = root/'index.sqlite'
        build_source_index(self.projects, db)
        self.repo = RepoTools(db, self.projects)
        self.docs = BM25()
        self.docs.add(Doc('memory', 'Memory', 'https://example.test', 'Memory lifecycle references'))
        self.case = SimpleNamespace(case_id='X', detector='StateHolderLeak', project='p',
                                    class_name='demo.Demo', source_path='Demo.java',
                                    raw_explanation="field 'retained' of type 'java.lang.Object'",
                                    gold_label='TP', review_notes='SECRET_LABEL')

    def test_tool_then_final_resolves_exact_source_and_no_gold(self):
        model = ScriptModel([tool('read_source', path='Demo.java', start_line=2, end_line=3), final(['E001'])])
        decision, evidence, trace = investigate(self.case, self.repo, self.docs, model)
        self.assertEqual(decision.parse_status, 'ok')
        self.assertEqual(decision.cited_code[0]['quote'], 'class Demo {\n Object retained;')
        self.assertEqual(decision.cited_code[0]['lines'], '2-3')
        self.assertEqual(len(trace), 2)
        self.assertIn('E001', model.prompts[1])
        self.assertNotIn('SECRET_LABEL', ''.join(model.prompts))
        self.assertNotIn('gold_label', ''.join(model.prompts))

    def test_unknown_evidence_id_rejected(self):
        decision, _, _ = investigate(self.case, self.repo, self.docs, ScriptModel([final(['E999'])]))
        self.assertEqual(decision.parse_status, 'schema_error')

    def test_invalid_final_type_rejected(self):
        action = final(); action['decision'] = []
        decision, _, _ = investigate(self.case, self.repo, self.docs, ScriptModel([action]))
        self.assertEqual(decision.parse_status, 'schema_error')

    def test_project_escape_and_unindexed_paths(self):
        session = ToolSession(self.case, self.repo, self.docs)
        for path in ('../other/Secret.java', 'C:\\Secret.java', '/tmp/Secret.java', 'missing.java'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                session.execute('read_source', {'path':path,'start_line':1,'end_line':2})

    def test_line_and_character_limits(self):
        session = ToolSession(self.case, self.repo, self.docs, max_evidence_chars=1)
        with self.assertRaises(ValueError):
            session.execute('read_source', {'path':'Demo.java','start_line':1,'end_line':61})
        with self.assertRaises(ValueError):
            session.execute('read_source', {'path':'Demo.java','start_line':1,'end_line':2})

    def test_tool_errors_return_to_model(self):
        actions = [tool('shell', command='ignored'), {'action':'final','decision':'inconclusive',
                   'confidence':.1,'reasoning':'Tool unavailable.','evidence_ids':[]}]
        model = ScriptModel(actions)
        _, _, trace = investigate(self.case, self.repo, self.docs, model)
        self.assertIn('error', trace[0]['tool_result'])
        self.assertIn('Unknown tool', model.prompts[1])

    def test_repeat_request_does_not_execute_twice(self):
        action = tool('find_symbol', name='Demo')
        _, _, trace = investigate(self.case, self.repo, self.docs, ScriptModel([action, action, final()]))
        self.assertIn('Repeated', trace[1]['tool_result']['error'])

    def test_turn_and_tool_limits(self):
        decision, _, _ = investigate(self.case, self.repo, self.docs,
            ScriptModel([tool('find_symbol',name='Demo')]), max_turns=1)
        self.assertEqual(decision.parse_status, 'budget_exhausted')
        decision, _, _ = investigate(self.case, self.repo, self.docs,
            ScriptModel([tool('find_symbol',name='Demo'),tool('find_symbol',name='Other')]), max_tool_calls=1)
        self.assertEqual(decision.parse_status, 'budget_exhausted')

    def test_docs_evidence_resolution(self):
        model = ScriptModel([tool('search_docs',query='memory'), final(['E001'])])
        decision, _, _ = investigate(self.case, self.repo, self.docs, model)
        self.assertEqual(decision.cited_docs[0]['doc_id'], 'memory')
        self.assertEqual(decision.cited_docs[0]['quote'], 'Memory lifecycle references')

    def test_empty_and_parse_failures_logged(self):
        for result, expected in ((GenerationResult('', 'script'), 'model_error'),
                                 (GenerationResult('broken', 'script'), 'parse_error')):
            decision, _, trace = investigate(self.case, self.repo, self.docs, ScriptModel([result]))
            self.assertEqual(decision.parse_status, expected)
            self.assertEqual(len(trace), 1)

    def test_incomplete_runtime_response_preserved(self):
        body = {'model':'', 'response':'', 'done':False}
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps(body).encode()
        with patch('urllib.request.urlopen', return_value=Response()):
            result = OllamaModel('test').generate('prompt')
        self.assertIn('incomplete', result.error)
        self.assertEqual(result.raw, body)
        self.assertEqual(result.model, 'test')

    def test_run_case_integration_and_trajectory_files(self):
        from leakagent.agent.loop import run_case
        self.case.detector_group = 'core'
        self.case.detector_recommendation = 'primary'
        self.case.to_dict = lambda: {'case_id': self.case.case_id}
        model = ScriptModel([
            tool('read_source', path='Demo.java', start_line=2, end_line=3),
            final(['E001']),
        ])
        logs = Path(self.tmp.name)/'logs'
        result = run_case(self.case, self.repo, self.docs, model,
                          collector_kwargs={'investigation_mode':'iterative'}, log_dir=logs)
        self.assertEqual(result.investigation_mode, 'iterative')
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.model_turns, 2)
        record = json.loads((logs/'X.json').read_text())
        self.assertEqual(record['result']['predicted_label'], 'TP')
        self.assertEqual(len(record['trajectory']), 2)
        self.assertTrue((logs/'X.trajectory.json').exists())

    def test_prompt_budget_stops_without_model_call(self):
        model = ScriptModel([])
        decision, _, _ = investigate(self.case, self.repo, self.docs, model, max_prompt_chars=1)
        self.assertEqual(decision.parse_status, 'budget_exhausted')
        self.assertFalse(model.prompts)
