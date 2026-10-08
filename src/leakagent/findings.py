def _sanitize_text(value: str) -> str:
    """Fix common mojibake from LeakScope's Windows console output."""
    if not value:
        return value
    try:
        # LeakScope sometimes emits Windows-1252 bytes re-encoded as UTF-8.
        repaired = value.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
        return repaired if repaired else value
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .constants import DETECTOR_FILES
from .source_index import lookup_source
from .text import content_hash, explanation_identity, simple_class, source_identity

def _write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def normalize_findings(input_dir: Path, output_path: Path, report_path: Path, source_db: Path | None = None) -> dict:
    input_dir, output_path, report_path = Path(input_dir), Path(output_path), Path(report_path)
    if not input_dir.is_dir(): raise FileNotFoundError(f"LeakScope artifact directory not found: {input_dir}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(source_db) if source_db else None
    detector_counts, mapping_counts, duplicate_counts, seen = Counter(), Counter(), Counter(), {}
    total = 0
    try:
        with output_path.open("w", encoding="utf-8") as out:
            for filename, detector in DETECTOR_FILES.items():
                path = input_dir / filename
                if not path.exists(): raise FileNotFoundError(f"Required detector output missing: {path}")
                records = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(records, list): raise ValueError(f"Expected a JSON array: {path}")
                for raw_index, record in enumerate(records):
                    total += 1; detector_counts[detector] += 1
                    project, source, explanation = str(record.get("project", "")).strip(), str(record.get("text_input", "")), str(record.get("explanation", ""))
                    source_hash = content_hash(source)
                    package_name, source_class, qualified_name = source_identity(source)
                    evidence_class, method_name, line_number = explanation_identity(explanation)
                    class_name = evidence_class or qualified_name or source_class
                    status, matches = lookup_source(conn, project, source_hash, class_name) if conn else ("not_indexed", [])
                    mapping_counts[status] += 1
                    identity = "\0".join((detector, project, source_hash, explanation))
                    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
                    base_id = f"LS-{digest}"; occurrence = seen.get(base_id, 0) + 1; seen[base_id] = occurrence
                    case_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
                    duplicate_of = base_id if occurrence > 1 else None
                    if duplicate_of: duplicate_counts[detector] += 1
                    selected = matches[0] if len(matches) == 1 else None
                    row = {
                        "case_id": case_id, "detector": detector, "project": project,
                        "raw_output": record.get("output"), "class_name": class_name,
                        "simple_class_name": simple_class(class_name), "method_name": method_name or None,
                        "line_number": line_number, "package_name": package_name or None,
                        "language": selected.get("language") if selected else ("java" if source else None),
                        "source_hash": source_hash, "source_path": selected.get("relative_path") if selected else None,
                        "source_mapping_status": status,
                        "source_candidates": [m["relative_path"] for m in matches] if len(matches) != 1 else [],
                        "raw_explanation": explanation, "raw_reference": {"file": filename, "array_index": raw_index},
                        "duplicate_of": duplicate_of,
                    }
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if conn: conn.close()
    report = {
        "total_cases": total, "detectors": dict(sorted(detector_counts.items())),
        "source_mapping": dict(sorted(mapping_counts.items())),
        "duplicate_records": sum(duplicate_counts.values()),
        "duplicates_by_detector": dict(sorted(duplicate_counts.items())),
        "input_directory": str(input_dir), "output": str(output_path),
    }
    _write_json(report_path, report)
    return report

