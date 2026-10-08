"""Evidence collection for a single InvestigationCase.

Collection is strategy-driven: each detector has its own plan (see strategies.py)
that specifies which lifecycle methods to fetch, whether to look up the source
of a referenced type, and how many code blocks to include.
"""

from dataclasses import dataclass, field

from ..docs.bm25 import BM25
from .candidates import InvestigationCase
from .repo_tools import RepoTools
from .strategies import extract_referenced_type, get_strategy


@dataclass
class CodeEvidence:
    path: str
    line_start: int
    line_end: int
    text: str
    role: str = "body"

    @property
    def lines_label(self) -> str:
        if self.line_start != self.line_end:
            return f"{self.line_start}-{self.line_end}"
        return str(self.line_start)


@dataclass
class ApiEvidence:
    path: str
    line_number: int
    line: str


@dataclass
class DocEvidence:
    doc_id: str
    title: str
    url: str
    score: float
    snippet: str


@dataclass
class EvidenceBundle:
    case_id: str
    detector: str
    warning_explanation: str
    code: list[CodeEvidence] = field(default_factory=list)
    api_hits: list[ApiEvidence] = field(default_factory=list)
    docs: list[DocEvidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "detector": self.detector,
            "warning_explanation": self.warning_explanation,
            "code": [
                {
                    "path": c.path,
                    "line_start": c.line_start,
                    "line_end": c.line_end,
                    "role": c.role,
                    "text": c.text,
                }
                for c in self.code
            ],
            "api_hits": [
                {"path": a.path, "line_number": a.line_number, "line": a.line}
                for a in self.api_hits
            ],
            "docs": [
                {"doc_id": d.doc_id, "title": d.title, "url": d.url, "score": d.score, "snippet": d.snippet}
                for d in self.docs
            ],
            "notes": list(self.notes),
        }


CLEANUP_PATTERNS: dict[str, list[str]] = {
    "FragmentViewFieldRetentionLeak": [r"onDestroyView", r"\bbinding\s*=\s*null", r"unbind\("],
    "ThreadedUIReference": [r"\bcancel\(", r"shutdownNow", r"\.interrupt\(", r"\.quit\(", r"lifecycleScope"],
    "StateHolderLeak": [r"onDestroy", r"(?<![=!<>])=(?!=)\s*null\b", r"getApplicationContext\(", r"AndroidViewModel"],
    "ServiceResourceManagementIssueDetector": [r"stopSelf\(", r"stopForeground\(", r"stopService\("],
    "ViewModelContextReference": [r"AndroidViewModel", r"getApplicationContext\("],
    "ImproperCallbackRegistration": [r"LifecycleOwner", r"removeCallback", r"addCallback\("],
    "BillingClientLeakRisk": [r"endConnection\("],
    "FlowRetentionLeak": [r"repeatOnLifecycle", r"lifecycleScope", r"collectLatest"],
}


def _looks_like_import_preamble(lines: list[str]) -> bool:
    if not lines:
        return True
    meaningful = 0
    imports = 0
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            continue
        meaningful += 1
        if s.startswith(("import ", "package ")):
            imports += 1
    if meaningful == 0:
        return True
    return imports / meaningful > 0.8


class EvidenceCollector:
    def __init__(
        self,
        repo_tools: RepoTools,
        docs_index: BM25,
        max_code_blocks: int = 4,
        max_api_hits: int = 10,
        max_docs: int = 3,
        max_lines_per_file: int = 120,
        max_api_files: int = 200,
        method_window: int = 45,
    ) -> None:
        self.repo = repo_tools
        self.docs = docs_index
        self.max_code_blocks = max_code_blocks
        self.max_api_hits = max_api_hits
        self.max_docs = max_docs
        self.max_lines_per_file = max_lines_per_file
        self.max_api_files = max_api_files
        self.method_window = method_window

    # ---------- low-level ----------

    def _read_file_block(self, project: str, relative_path: str, role: str = "file") -> CodeEvidence | None:
        text = self.repo.read_source(project, relative_path)
        if not text:
            return None
        lines = text.splitlines()
        limit = 400 if role == "referenced_type" else self.max_lines_per_file
        if len(lines) > limit:
            lines = lines[:limit]
        if role == "file" and _looks_like_import_preamble(lines):
            return None
        return CodeEvidence(
            path=relative_path,
            line_start=1,
            line_end=len(lines),
            text="\n".join(lines),
            role=role,
        )

    def _method_body(self, project: str, relative_path: str, line_number: int, role: str) -> CodeEvidence | None:
        text = self.repo.read_source(project, relative_path)
        if not text:
            return None
        file_lines = text.splitlines()
        start = max(0, line_number - 1)
        end = min(len(file_lines), start + self.method_window)
        snippet = "\n".join(file_lines[start:end])
        return CodeEvidence(
            path=relative_path,
            line_start=start + 1,
            line_end=end,
            text=snippet,
            role=role,
        )

    # ---------- collection steps ----------

    def _fetch_lifecycle_methods(self, case: InvestigationCase, strategy, cap: int) -> list[CodeEvidence]:
        blocks: list[CodeEvidence] = []
        for method_name in strategy.lifecycle_methods:
            hits = self.repo.find_method(case.project, case.class_name, method_name, max_hits=1)
            for hit in hits:
                block = self._method_body(
                    case.project, hit.relative_path, hit.line_number, f"lifecycle:{method_name}"
                )
                if block:
                    blocks.append(block)
                    break
            if len(blocks) >= cap:
                break
        return blocks

    def _fetch_referenced_type(self, case: InvestigationCase, strategy) -> list[CodeEvidence]:
        if not strategy.include_referenced_types:
            return []
        ref = extract_referenced_type(case.raw_explanation or "")
        if not ref:
            return []

        import re
        queue = [(ref, 0)]
        visited = set()
        blocks = []
        # At most three files, two dependency hops, and 180 lines per file.
        while queue and len(blocks) < 3:
            name, depth = queue.pop(0)
            hits = self.repo.find_symbol(case.project, name, max_hits=20)
            exact = [h for h in hits if h.qualified_name == name]
            hits = exact or hits
            if len(hits) != 1:
                continue
            hit = hits[0]
            if hit.relative_path in visited:
                continue
            visited.add(hit.relative_path)
            source = self.repo.read_source(case.project, hit.relative_path)
            if not source:
                continue

            lines = source.splitlines()
            # Skip leading license text while preserving actual line numbers.
            first = next(
                (i for i, line in enumerate(lines)
                 if line.strip().startswith("package ")),
                0,
            )
            end = min(len(lines), first + 180)
            blocks.append(CodeEvidence(
                path=hit.relative_path,
                line_start=first + 1,
                line_end=end,
                text="\n".join(lines[first:end]),
                role="referenced_type" if depth == 0 else f"type_dependency:{depth}",
            ))
            if depth >= 2:
                continue

            imports = {
                value.rsplit(".", 1)[-1]: value
                for value in re.findall(
                    r"^\s*import\s+([\w.]+)\s*;", source, re.MULTILINE
                )
            }
            # Follow only declarations visible in the supplied excerpt.
            excerpt = "\n".join(lines[first:end])
            dependencies = re.findall(r"\bextends\s+([\w.]+)", excerpt)
            dependencies += re.findall(
                r"\b(?:private|protected|public)\s+"
                r"(?:(?:static|final|volatile|transient)\s+)*"
                r"([\w.]+)\s+\w+\s*(?:[;=])",
                excerpt,
            )
            dependencies += re.findall(
                r"\bpublic\s+([\w.]+)\s+get\w+\s*\(", excerpt
            )
            for dependency in dict.fromkeys(dependencies):
                qualified = imports.get(dependency, dependency)
                queue.append((qualified, depth + 1))
        return blocks

    def _fetch_case_method(self, case: InvestigationCase, cap: int) -> list[CodeEvidence]:
        if not case.method_name:
            return []
        hits = self.repo.find_method(case.project, case.class_name, case.method_name, max_hits=1)
        blocks: list[CodeEvidence] = []
        for hit in hits:
            block = self._method_body(
                case.project, hit.relative_path, hit.line_number, f"method:{case.method_name}"
            )
            if block:
                blocks.append(block)
        return blocks[:cap]

    def _api_hits(self, case: InvestigationCase) -> list[ApiEvidence]:
        patterns = CLEANUP_PATTERNS.get(case.detector, [])
        if not patterns:
            return []
        combined = "|".join(f"(?:{p})" for p in patterns)
        # Search the candidate file directly so unrelated project hits
        # cannot consume the evidence budget.
        if not case.source_path:
            return []
        source = self.repo.read_source(case.project, case.source_path)
        if not source:
            return []
        import re
        pattern = re.compile(combined)
        matches = []
        for number, line in enumerate(source.splitlines(), 1):
            if pattern.search(line):
                matches.append(ApiEvidence(
                    path=case.source_path,
                    line_number=number,
                    line=line.strip(),
                ))
                if len(matches) >= self.max_api_hits:
                    break
        return matches
        return [
            ApiEvidence(path=h.relative_path, line_number=h.line_number, line=h.line)
            for h in hits
        ]

    def _docs(self, case: InvestigationCase) -> list[DocEvidence]:
        query_terms = [
            case.detector.replace("Leak", " leak").replace("View", " view"),
            case.class_name,
            (case.method_name or ""),
        ]
        query = " ".join(t for t in query_terms if t)
        try:
            hits = self.docs.search(query, top_k=self.max_docs)
        except Exception:
            return []
        return [
            DocEvidence(
                doc_id=h.doc_id,
                title=h.title,
                url=h.url,
                score=h.score,
                snippet=h.snippet,
            )
            for h in hits
        ]

    # ---------- public ----------

    def collect(self, case: InvestigationCase) -> EvidenceBundle:
        strategy = get_strategy(case.detector)
        bundle = EvidenceBundle(
            case_id=case.case_id,
            detector=case.detector,
            warning_explanation=case.raw_explanation,
        )

        cap = min(strategy.max_code_blocks, self.max_code_blocks)

        # 1. Lifecycle methods — the most likely place for the answer.
        for block in self._fetch_lifecycle_methods(case, strategy, cap):
            if len(bundle.code) >= cap:
                break
            bundle.code.append(block)

        # 2. Referenced type (StateHolder only).
        if len(bundle.code) < cap:
            for block in self._fetch_referenced_type(case, strategy):
                if len(bundle.code) >= cap:
                    break
                bundle.code.append(block)

        if strategy.include_referenced_types:
            ref = extract_referenced_type(case.raw_explanation or "")
            referenced = [b for b in bundle.code if b.role == "referenced_type"]
            if not ref:
                bundle.notes.append("Referenced type could not be extracted.")
            elif not referenced:
                bundle.notes.append(
                    f"Referenced type {ref} was not included: lookup may have "
                    "failed or the code-block budget may have been exhausted."
                )
            else:
                for block in referenced:
                    source = self.repo.read_source(case.project, block.path)
                    total = len(source.splitlines()) if source else 0
                    bundle.notes.append(
                        f"Referenced type {ref}: showing lines {block.line_start}-{block.line_end} "
                        f"of {total} lines from {block.path}. "
                        "Unshown code and transitive references remain unresolved."
                    )

        if strategy.include_referenced_types:
            bundle.notes.append(
                "Type retrieval is heuristic: at most three files, two hops, "
                "and 180 lines per file. Generic contents, unshown declarations, "
                "ambiguous or missing types, and Kotlin relationships may remain "
                "unresolved. Retrieved excerpts do not prove absence of UI retention."
            )

        # 3. The method named in the analyzer explanation.
        if len(bundle.code) < cap:
            for block in self._fetch_case_method(case, cap):
                if len(bundle.code) >= cap:
                    break
                bundle.code.append(block)

        # 4. Fallback: the file at source_path.
        if len(bundle.code) < cap and case.source_path:
            block = self._read_file_block(case.project, case.source_path, role="file")
            if block:
                bundle.code.append(block)

        # Deduplicate by (path, line_start, line_end).
        seen = set()
        deduped = []
        for block in bundle.code:
            key = (block.path, block.line_start, block.line_end)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(block)
        bundle.code = deduped[:cap]

        bundle.api_hits = self._api_hits(case)
        bundle.notes.append(
            "Cleanup API search is limited to the candidate source file. "
            "Delegated or inherited cleanup is not resolved by this search."
        )
        bundle.docs = self._docs(case)

        if not bundle.code:
            bundle.notes.append("No source file resolved for this case; conclusions must rely on docs only.")
        return bundle