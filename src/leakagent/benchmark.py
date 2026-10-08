import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .constants import PAPER_TABLE_VII, canonical_detector, detector_group
from .text import class_leaf, normalize_method, simple_class

def _normalize_label(value: str) -> str:
    label = (value or "").strip().upper()
    if label in {"UNS", "UNSURE"}: return "UNSURE"
    if label in {"TP", "FP"}: return label
    raise ValueError(f"Unsupported validation label: {value!r}")

def _key(detector: str, project: str, class_name: str) -> tuple[str, str, str]:
    return canonical_detector(detector), (project or "").strip().casefold(), class_leaf(class_name).casefold()

def normalize_benchmark(input_csv: Path, findings_path: Path, output_path: Path, report_path: Path, label_column: str = "Annotator_1_Label", label_provenance: str = "Final adjudicated LeakScope paper label") -> dict:
    input_csv, findings_path, output_path, report_path = map(Path, (input_csv, findings_path, output_path, report_path))
    findings = [json.loads(line) for line in findings_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    exact, outer, class_method, outer_method, project_method, by_project = (defaultdict(list) for _ in range(6))
    for item in findings:
        detector, project, class_name = item["detector"], item["project"], item.get("class_name", "")
        method = normalize_method(item.get("method_name", "")).casefold()
        exact_key, project_key = _key(detector, project, class_name), (detector, project.strip().casefold())
        outer_key = (detector, project_key[1], simple_class(class_name).casefold())
        exact[exact_key].append(item); outer[outer_key].append(item); by_project[project_key].append(item)
        if method:
            class_method[exact_key + (method,)].append(item); outer_method[outer_key + (method,)].append(item); project_method[project_key + (method,)].append(item)
    with input_csv.open(encoding="utf-8-sig", newline="") as stream: rows = list(csv.DictReader(stream))
    if not rows: raise ValueError(f"Validation CSV is empty: {input_csv}")
    detector_column = "Detector" if "Detector" in rows[0] else "l" if "l" in rows[0] else None
    if not detector_column: raise ValueError("Validation CSV needs a Detector column; the known export also uses 'l'.")
    if label_column not in rows[0]: raise ValueError(f"Label column not found: {label_column}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    label_counts, detector_counts, link_counts = Counter(), defaultdict(Counter), Counter()
    with output_path.open("w", encoding="utf-8") as out:
        for position, raw in enumerate(rows, 1):
            detector, project, class_name = canonical_detector(raw[detector_column]), raw.get("Project", "").strip(), raw.get("Class", "").strip()
            label, method = _normalize_label(raw.get(label_column, "")), normalize_method(raw.get("Method", "")).casefold()
            exact_key, project_key = _key(detector, project, class_name), (detector, project.casefold())
            outer_key = (detector, project.casefold(), simple_class(class_name).casefold())
            attempts = []
            if method: attempts.extend(((class_method.get(exact_key + (method,), []), "exact_detector_project_class_method"), (outer_method.get(outer_key + (method,), []), "outer_class_method_fallback"), (project_method.get(project_key + (method,), []), "unique_detector_project_method_fallback")))
            attempts.extend(((exact.get(exact_key, []), "exact_detector_project_class"), (outer.get(outer_key, []), "outer_class_fallback"), (by_project.get(project_key, []), "unique_detector_project_fallback")))
            candidates, status = [], "unmatched"
            for possible, possible_status in attempts:
                if len(possible) == 1: candidates, status = possible, possible_status; break
                if len(possible) > 1 and not candidates: candidates, status = possible, "ambiguous"
            selected = candidates[0] if len(candidates) == 1 else None
            link_counts[status] += 1; label_counts[label] += 1; detector_counts[detector][label] += 1
            raw_id = raw.get("ID", "").strip() or str(position)
            row = {
                "benchmark_id": f"VAL-{int(raw_id):03d}" if raw_id.isdigit() else f"VAL-{raw_id}",
                "candidate_id": selected.get("case_id") if selected else None,
                "detector": detector, "detector_group": detector_group(detector), "project": project,
                "class_name": class_name or (selected.get("class_name") if selected else None),
                "method_name": raw.get("Method", "").strip() or None,
                "violation_details": raw.get("Violation_Details", "").strip(),
                "gold_label": label, "review_notes": raw.get("Notes", "").strip() or None,
                "label_source_column": label_column, "label_provenance": label_provenance,
                "candidate_link_status": status,
                "source_path": selected.get("source_path") if selected else None,
                "source_mapping_status": selected.get("source_mapping_status") if selected else None,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    observed = {det: {label: detector_counts[det].get(label, 0) for label in ("TP", "FP", "UNSURE")} for det in sorted(detector_counts)}
    paper_match = observed == PAPER_TABLE_VII
    report = {
        "total_cases": len(rows), "labels": dict(label_counts), "detectors": observed,
        "candidate_linkage": dict(sorted(link_counts.items())), "matches_submitted_paper_table_vii": paper_match,
        "label_column": label_column, "label_provenance": label_provenance,
        "input": str(input_csv), "output": str(output_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
