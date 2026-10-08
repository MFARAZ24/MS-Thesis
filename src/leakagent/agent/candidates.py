"""Load normalized LeakScope cases and join them with the 388-case gold benchmark."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

from ..constants import detector_group

# Evaluation roles derived from the LeakScope paper's Table VII precision data.
# primary     -> LeakAgent is expected to measurably reduce false positives here
# supporting  -> LeakAgent helps, but the family is smaller or already precise
# control     -> LeakAgent must NOT dismiss correct warnings (non-regression)
# calibration -> detector known to be imprecise; agent behavior studied separately
# excluded    -> auxiliary modernization signal; outside primary leak claims
DETECTOR_RECOMMENDATION: dict[str, str] = {
    "StateHolderLeak": "primary",
    "ThreadedUIReference": "primary",
    "ServiceResourceManagementIssueDetector": "supporting",
    "FragmentViewFieldRetentionLeak": "control",
    "ImproperCallbackRegistration": "control",
    "ViewModelContextReference": "control",
    "BillingClientLeakRisk": "control",
    "FlowRetentionLeak": "calibration",
    "ViewBindingOpportunity": "excluded",
}


@dataclass
class InvestigationCase:
    case_id: str
    detector: str
    detector_group: str
    detector_recommendation: str
    project: str
    class_name: str
    simple_class_name: str
    method_name: Optional[str]
    line_number: Optional[int]
    package_name: Optional[str]
    language: Optional[str]
    source_path: Optional[str]
    source_hash: str
    source_mapping_status: str
    raw_explanation: str
    violation_details: str
    is_gold: bool
    benchmark_id: Optional[str]
    gold_label: Optional[str]
    review_notes: Optional[str]
    candidate_link_status: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _iter_jsonl(path: Path) -> Iterator[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def load_investigation_cases(
    cases_path: Path,
    gold_path: Optional[Path] = None,
) -> list[InvestigationCase]:
    """Read normalized LeakScope cases and (optionally) the 388-case gold set.

    Cases that appear in the gold file are returned with `is_gold=True` and
    their `gold_label` / `review_notes` populated. Cases without a gold row are
    returned with `is_gold=False`.
    """
    cases_path = Path(cases_path)
    if not cases_path.is_file():
        raise FileNotFoundError(f"Normalized cases file not found: {cases_path}")

    raw_by_id: dict[str, dict] = {}
    for rec in _iter_jsonl(cases_path):
        raw_by_id[rec["case_id"]] = rec

    gold_by_candidate: dict[str, dict] = {}
    if gold_path is not None:
        gold_path = Path(gold_path)
        if not gold_path.is_file():
            raise FileNotFoundError(f"Gold benchmark file not found: {gold_path}")
        for rec in _iter_jsonl(gold_path):
            candidate_id = rec.get("candidate_id") or rec.get("case_id")
            if candidate_id:
                gold_by_candidate[candidate_id] = rec

    result: list[InvestigationCase] = []
    for case_id, raw in raw_by_id.items():
        gold = gold_by_candidate.get(case_id)
        detector = raw.get("detector", "")
        result.append(
            InvestigationCase(
                case_id=case_id,
                detector=detector,
                detector_group=_group_for(detector),
                detector_recommendation=DETECTOR_RECOMMENDATION.get(detector, "unknown"),
                project=raw.get("project", ""),
                class_name=raw.get("class_name") or "",
                simple_class_name=raw.get("simple_class_name") or "",
                method_name=raw.get("method_name"),
                line_number=raw.get("line_number"),
                package_name=raw.get("package_name"),
                language=raw.get("language"),
                source_path=raw.get("source_path"),
                source_hash=raw.get("source_hash", ""),
                source_mapping_status=raw.get("source_mapping_status", ""),
                raw_explanation=raw.get("raw_explanation", ""),
                violation_details=(gold or {}).get("violation_details", ""),
                is_gold=gold is not None,
                benchmark_id=(gold or {}).get("benchmark_id"),
                gold_label=(gold or {}).get("gold_label"),
                review_notes=(gold or {}).get("review_notes"),
                candidate_link_status=(gold or {}).get("candidate_link_status"),
            )
        )
    return result


def _group_for(detector: str) -> str:
    try:
        return detector_group(detector)
    except Exception:
        return "unknown"