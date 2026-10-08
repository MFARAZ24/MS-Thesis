"""Read-only repository access for LeakAgent, backed by the source index."""

import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SymbolHit:
    project: str
    relative_path: str
    language: str
    package_name: str
    qualified_name: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MethodHit:
    project: str
    relative_path: str
    class_name: str
    method_name: str
    line_number: int
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApiCallHit:
    project: str
    relative_path: str
    line_number: int
    line: str
    enclosing_symbol: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


class RepoTools:
    """Thin, dependency-free repository access layer.

    All lookups are scoped to a single project. The layer is intentionally
    read-only and cacheless across processes so that a LeakAgent run is fully
    reproducible from the SQLite index plus the on-disk source tree.
    """

    def __init__(self, source_index_db: Path, projects_root: Path):
        self.db_path = Path(source_index_db)
        self.projects_root = Path(projects_root)
        if not self.db_path.is_file():
            raise FileNotFoundError(f"Source index not found: {self.db_path}")
        if not self.projects_root.is_dir():
            raise FileNotFoundError(f"Projects root not found: {self.projects_root}")
        self._source_cache: dict[tuple[str, str], Optional[str]] = {}

    # ---------- low-level ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _project_files(self, project: str, language: Optional[str] = None) -> list[dict]:
        query = (
            "SELECT relative_path, language, package_name, qualified_name, top_level_name "
            "FROM sources WHERE project=?"
        )
        params: list = [project]
        if language:
            query += " AND language=?"
            params.append(language)
        query += " ORDER BY relative_path"
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(query, params)]

    # ---------- public tools ----------

    def read_source(self, project: str, relative_path: str) -> Optional[str]:
        key = (project, relative_path)
        if key in self._source_cache:
            return self._source_cache[key]
        path = self.projects_root / project / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
        self._source_cache[key] = text
        return text

    def list_project_files(self, project: str, language: Optional[str] = None) -> list[dict]:
        return self._project_files(project, language)

    def find_symbol(self, project: str, name: str, max_hits: int = 50) -> list[SymbolHit]:
        """Find a class / interface / enum by simple or qualified name."""
        if not name:
            return []
        simple = name.rsplit(".", 1)[-1].split("$", 1)[0]
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT relative_path, language, package_name, qualified_name, top_level_name "
                "FROM sources WHERE project=? AND "
                "(top_level_name=? OR qualified_name=? OR qualified_name LIKE ?) "
                "ORDER BY relative_path LIMIT ?",
                (project, simple, name, f"%.{name}", max_hits),
            ).fetchall()
        return [
            SymbolHit(
                project=project,
                relative_path=r["relative_path"],
                language=r["language"],
                package_name=r["package_name"],
                qualified_name=r["qualified_name"],
            )
            for r in rows
        ]

    def find_method(
        self,
        project: str,
        class_name: str,
        method_name: str,
        max_hits: int = 20,
    ) -> list[MethodHit]:
        """Locate method declaration candidates inside the named class (heuristic).

        Strategy: resolve the class to one or more files via the index, then
        regex-scan those files for the method name. The regex excludes
        `foo.bar(` calls by requiring the name not be preceded by `.`.
        """
        if not method_name:
            return []
        symbols = self.find_symbol(project, class_name)
        if not symbols:
            return []
        pattern = re.compile(rf"(?<![.\w$]){re.escape(method_name)}\s*\(")
        hits: list[MethodHit] = []
        for symbol in symbols:
            text = self.read_source(project, symbol.relative_path)
            if not text:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(
                        MethodHit(
                            project=project,
                            relative_path=symbol.relative_path,
                            class_name=symbol.qualified_name or symbol.relative_path,
                            method_name=method_name,
                            line_number=lineno,
                            snippet=line.strip(),
                        )
                    )
                    if len(hits) >= max_hits:
                        return hits
        return hits

    def find_api_calls(
        self,
        project: str,
        api_pattern: str,
        language: Optional[str] = None,
        max_hits: int = 100,
        max_files: int = 500,
    ) -> list[ApiCallHit]:
        """Regex-search for API references across a project's source files."""
        if not api_pattern:
            return []
        try:
            pattern = re.compile(api_pattern)
        except re.error as exc:
            raise ValueError(f"Invalid API pattern: {exc}") from exc
        files = self._project_files(project, language)
        hits: list[ApiCallHit] = []
        scanned = 0
        for file_record in files:
            if scanned >= max_files:
                break
            scanned += 1
            text = self.read_source(project, file_record["relative_path"])
            if not text:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(
                        ApiCallHit(
                            project=project,
                            relative_path=file_record["relative_path"],
                            line_number=lineno,
                            line=line.strip(),
                            enclosing_symbol=file_record["qualified_name"]
                            or file_record["top_level_name"],
                        )
                    )
                    if len(hits) >= max_hits:
                        return hits
        return hits