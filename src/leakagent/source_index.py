import json
import os
import sqlite3
from pathlib import Path

from .constants import IGNORED_SOURCE_DIRS
from .text import content_hash, source_identity

SCHEMA = """
DROP TABLE IF EXISTS sources;
CREATE TABLE sources (
  project TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  language TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  package_name TEXT NOT NULL,
  top_level_name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  PRIMARY KEY (project, relative_path)
);
CREATE INDEX idx_sources_project_hash ON sources(project, content_hash);
CREATE INDEX idx_sources_project_class ON sources(project, top_level_name);
"""


def _source_files(project_dir: Path):
    """Index ordinary source plus generated Java/Kotlin under build/generated."""
    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)
        kept = []
        for directory in sorted(dirs):
            if directory == "build":
                # Enter build only to visit its generated-source subtree.
                if (root_path / directory / "generated").is_dir():
                    kept.append(directory)
            elif directory not in IGNORED_SOURCE_DIRS:
                kept.append(directory)

        if root_path.name == "build":
            kept = [directory for directory in kept if directory == "generated"]
        dirs[:] = kept

        for name in sorted(files):
            if Path(name).suffix.lower() in {".java", ".kt"}:
                yield root_path / name


def build_source_index(projects_root: Path, db_path: Path, progress: bool = False) -> dict:
    projects_root, db_path = Path(projects_root), Path(db_path)
    if not projects_root.is_dir():
        raise FileNotFoundError(f"Projects root not found: {projects_root}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"projects": 0, "java_files": 0, "kotlin_files": 0, "read_errors": 0}
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        batch = []
        for project_dir in sorted(p for p in projects_root.iterdir() if p.is_dir()):
            counts["projects"] += 1
            for path in _source_files(project_dir):
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    counts["read_errors"] += 1
                    continue
                package_name, top_level_name, qualified_name = source_identity(text)
                stat, language = path.stat(), "java" if path.suffix.lower() == ".java" else "kotlin"
                counts[f"{language}_files"] += 1
                batch.append(
                    (
                        project_dir.name,
                        path.relative_to(project_dir).as_posix(),
                        language,
                        content_hash(text),
                        package_name,
                        top_level_name,
                        qualified_name,
                        stat.st_size,
                        stat.st_mtime_ns,
                    )
                )
                if len(batch) >= 2000:
                    conn.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)", batch)
                    batch.clear()
            if batch:
                conn.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
            if progress and counts["projects"] % 25 == 0:
                print(
                    f"Indexed {counts['projects']} projects "
                    f"({counts['java_files']} Java, {counts['kotlin_files']} Kotlin files)...",
                    flush=True,
                )
        conn.commit()
    finally:
        conn.close()
    return counts | {"database": str(db_path)}


def lookup_source(conn: sqlite3.Connection, project: str, source_hash: str, class_name: str) -> tuple[str, list[dict]]:
    conn.row_factory = sqlite3.Row
    exact = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM sources WHERE project=? AND content_hash=? ORDER BY relative_path",
            (project, source_hash),
        )
    ]
    if len(exact) == 1:
        return "exact_hash", exact
    if len(exact) > 1:
        return "ambiguous_hash", exact
    simple = (class_name or "").rsplit(".", 1)[-1].split("$", 1)[0]
    by_class = (
        [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sources WHERE project=? AND top_level_name=? ORDER BY relative_path",
                (project, simple),
            )
        ]
        if simple
        else []
    )
    if len(by_class) == 1:
        return "unique_class_fallback", by_class
    if len(by_class) > 1:
        return "ambiguous_class_fallback", by_class
    return "unmatched", []