import json
import tempfile
import unittest
from pathlib import Path

from leakagent.docs.bm25 import BM25, Doc
from leakagent.docs.corpus import load_corpus
from leakagent.docs.html_text import html_to_text


class DocsTest(unittest.TestCase):
    def test_bm25_ranks_matching_doc_first(self):
        index = BM25()
        index.add(Doc("a", "Fragment lifecycle", "u1",
                      "Clear the binding reference in onDestroyView to release the view hierarchy."))
        index.add(Doc("b", "Services overview", "u2",
                      "A started service should call stopSelf when its work is complete."))
        index.add(Doc("c", "Threading", "u3",
                      "Worker threads that capture UI objects delay garbage collection."))
        hits = index.search("onDestroyView clear binding", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0].doc_id, "a")

    def test_html_to_text_strips_script_and_tags(self):
        html = "<html><head><script>var x=1;</script></head><body><p>Hello <b>world</b>.</p></body></html>"
        text = html_to_text(html)
        self.assertIn("Hello", text)
        self.assertIn("world", text)
        self.assertNotIn("var x", text)

    def test_load_corpus_reads_json_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "d1.json").write_text(
                json.dumps({
                    "slug": "d1", "title": "T1", "url": "u", "text": "body"
                }),
                encoding="utf-8",
            )
            docs = load_corpus(root)
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].doc_id, "d1")


if __name__ == "__main__":
    unittest.main()