"""Prepare LeakAgent artifacts: unified cases, dev/test split, per-split gold."""

import json
from collections import Counter
from pathlib import Path

from .candidates import InvestigationCase, load_investigation_cases
from .split import deterministic_split


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _detector_counts(cases: list[InvestigationCase]) -> dict[str, int]:
    return dict(sorted(Counter(c.detector for c in cases).items()))


def prepare_agent(
    cases_path: Path,
    gold_path: Path,
    output_dir: Path,
    dev_ratio: float = 0.5,
    seed: str = "leakagent-v1",
) -> dict:
    cases_path = Path(cases_path)
    gold_path = Path(gold_path)
    output_dir = Path(output_dir)

    cases = load_investigation_cases(cases_path, gold_path)
    gold = [c for c in cases if c.is_gold]

    all_projects = sorted({c.project for c in cases})
    dev_projects, test_projects = deterministic_split(all_projects, dev_ratio=dev_ratio, seed=seed)
    dev_set, test_set = set(dev_projects), set(test_projects)

    dev_cases = [c for c in cases if c.project in dev_set]
    test_cases = [c for c in cases if c.project in test_set]
    dev_gold = [c for c in dev_cases if c.is_gold]
    test_gold = [c for c in test_cases if c.is_gold]

    _write_jsonl(output_dir / "cases.jsonl", [c.to_dict() for c in cases])
    _write_jsonl(output_dir / "gold.jsonl", [c.to_dict() for c in gold])
    _write_jsonl(output_dir / "dev_cases.jsonl", [c.to_dict() for c in dev_cases])
    _write_jsonl(output_dir / "test_cases.jsonl", [c.to_dict() for c in test_cases])
    _write_jsonl(output_dir / "dev_gold.jsonl", [c.to_dict() for c in dev_gold])
    _write_jsonl(output_dir / "test_gold.jsonl", [c.to_dict() for c in test_gold])

    _write_json(
        output_dir / "split.json",
        {
            "seed": seed,
            "dev_ratio": dev_ratio,
            "total_projects": len(all_projects),
            "dev_projects": dev_projects,
            "test_projects": test_projects,
        },
    )

    all_detectors = set(_detector_counts(gold).keys())
    dev_detectors = set(_detector_counts(dev_gold).keys())
    test_detectors = set(_detector_counts(test_gold).keys())

    report = {
        "cases_path": str(cases_path),
        "gold_path": str(gold_path),
        "output_dir": str(output_dir),
        "seed": seed,
        "dev_ratio": dev_ratio,
        "total_cases": len(cases),
        "total_gold": len(gold),
        "total_projects": len(all_projects),
        "dev_projects": len(dev_projects),
        "test_projects": len(test_projects),
        "dev_cases": len(dev_cases),
        "test_cases": len(test_cases),
        "dev_gold": len(dev_gold),
        "test_gold": len(test_gold),
        "dev_cases_by_detector": _detector_counts(dev_cases),
        "test_cases_by_detector": _detector_counts(test_cases),
        "dev_gold_by_detector": _detector_counts(dev_gold),
        "test_gold_by_detector": _detector_counts(test_gold),
        "detectors_missing_in_dev": sorted(all_detectors - dev_detectors),
        "detectors_missing_in_test": sorted(all_detectors - test_detectors),
    }
    _write_json(output_dir / "prepare_report.json", report)
    return report